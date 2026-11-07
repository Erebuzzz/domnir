"""Ragnarok Red/Blue Autonomous Adversarial Co-Evolution Arena.

Implements the complete 12-step autonomous engineering loop:
Specify -> Synthesize (Blue) -> Baseline -> Attack (Red) -> Verify -> Minimize ->
Diagnose -> Regression -> Holdout -> Co-evolve -> Decide -> Publish.
"""

from __future__ import annotations

import hashlib
import time
from enum import Enum
from typing import Any, Callable, Sequence
from pydantic import BaseModel, Field

from domnir.contracts.stl import SafetyContract, STLRobustnessResult
from domnir.inference.vultr import VultrInferenceClient
from domnir.scenario import ScenarioParameter, calculate_applied_disturbance
from domnir.spec import FlightSpec, GeneratedController
from .minimize import CounterexampleMinimizer, MinimizationResult
from .repair import AutonomousRepairEngine, HoldoutSuite, RepairAttempt, RepairCampaignResult
from .search import (
    DifferentialEvolutionFalsifier,
    FalsificationCampaignResult,
    FalsificationCandidate,
    RagnarokSearchSpace,
    SobolBaselineFalsifier,
)


class ArenaPhase(str, Enum):
    SPECIFY = "SPECIFY"
    SYNTHESIZE = "SYNTHESIZE"
    BASELINE = "BASELINE"
    ATTACK = "ATTACK"
    VERIFY = "VERIFY"
    MINIMIZE = "MINIMIZE"
    DIAGNOSE = "DIAGNOSE"
    REGRESSION = "REGRESSION"
    HOLDOUT = "HOLDOUT"
    CO_EVOLVE = "CO_EVOLVE"
    DECIDE = "DECIDE"
    PUBLISH = "PUBLISH"


class ArenaRoundOutcome(str, Enum):
    REVISION_ACCEPTED = "REVISION_ACCEPTED"
    REVISION_REJECTED = "REVISION_REJECTED"
    NO_COUNTEREXAMPLE_FOUND = "NO_COUNTEREXAMPLE_FOUND"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    SIMULATION_ERROR = "SIMULATION_ERROR"


class ArenaRoundReport(BaseModel):
    round_index: int
    controller_sha256: str
    phase: ArenaPhase
    outcome: ArenaRoundOutcome
    nominal_baseline_passed: bool
    falsification_evaluations: int = 0
    falsification_violations: int = 0
    witness_found: bool = False
    witness_scenario: dict[str, Any] | None = None
    minimized_scenario: dict[str, Any] | None = None
    cost_reduction_ratio: float = 0.0
    repair_attempted: bool = False
    repaired_controller_sha256: str | None = None
    regression_passed: bool = False
    holdout_passed: bool = False
    holdout_pass_rate: float = 0.0
    summary: str = ""
    provenance_chain: list[dict[str, Any]] = Field(default_factory=list)


class ArenaCampaignReport(BaseModel):
    campaign_id: str
    target_altitude_m: float
    total_rounds_executed: int
    final_controller: GeneratedController | None
    initial_controller_sha256: str
    final_controller_sha256: str | None
    rounds: list[ArenaRoundReport] = Field(default_factory=list)
    accumulated_regression_suite_size: int = 0
    summary: str = ""
    limitation_note: str = (
        "Passing a finite collection of test scenarios does not constitute a formal proof of universal flight safety."
    )


def _dump_scenario(scen: ScenarioParameter | None) -> dict[str, Any] | None:
    if scen is None:
        return None
    if hasattr(scen, "to_dict"):
        return scen.to_dict()
    if hasattr(scen, "model_dump"):
        return scen.model_dump()
    return dict(scen)


class RedBlueArenaOrchestrator:
    """Coordinates autonomous adversarial co-evolution between Red-team search and Blue-team repair."""

    def __init__(
        self,
        contract: SafetyContract,
        evaluator: Callable[[GeneratedController, ScenarioParameter], STLRobustnessResult],
        *,
        inference_client: VultrInferenceClient | None = None,
        search_budget_per_round: int = 20,
        max_repair_revisions: int = 2,
    ) -> None:
        self.contract = contract
        self.evaluator = evaluator
        self.inference_client = inference_client
        self.search_budget = search_budget_per_round
        self.max_repair_revisions = max_repair_revisions
        self.search_space = RagnarokSearchSpace.from_contract(contract)
        self.minimizer = CounterexampleMinimizer(target_altitude_m=contract.target_altitude_m)
        self.accumulated_regressions: list[ScenarioParameter] = []

    def run_campaign(
        self,
        initial_controller: GeneratedController,
        max_rounds: int = 2,
        *,
        candidate_generator: Callable[[str], str] | None = None,
    ) -> ArenaCampaignReport:
        campaign_id = f"arena-{hashlib.sha256(str(time.time()).encode()).hexdigest()[:12]}"
        curr_ctrl = initial_controller
        round_reports: list[ArenaRoundReport] = []

        for round_idx in range(1, max_rounds + 1):
            provenance: list[dict[str, Any]] = []

            # 1. SPECIFY: Contract parameters
            provenance.append({
                "phase": ArenaPhase.SPECIFY.value,
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "target_altitude_m": self.contract.target_altitude_m,
                "corridor_m": self.contract.altitude_tolerance_m,
            })

            # 2. BASELINE: Test nominal hover calm conditions
            nominal_scen = ScenarioParameter(
                initial_altitude_m=self.contract.target_altitude_m,
                disturbance_force_z=0.0,
            )
            nom_res = self.evaluator(curr_ctrl, nominal_scen)
            baseline_ok = bool(nom_res.satisfied and getattr(nom_res, "is_valid", True))
            provenance.append({
                "phase": ArenaPhase.BASELINE.value,
                "passed": baseline_ok,
                "robustness": float(nom_res.min_robustness),
            })

            # Also verify against previously accumulated regressions
            regression_clean = True
            for reg_scen in self.accumulated_regressions:
                reg_res = self.evaluator(curr_ctrl, reg_scen)
                if not reg_res.satisfied:
                    regression_clean = False
                    break

            # 3. ATTACK (Red Team): Adaptive numerical falsification search
            def search_eval(s: ScenarioParameter) -> STLRobustnessResult:
                return self.evaluator(curr_ctrl, s)

            de_falsifier = DifferentialEvolutionFalsifier(
                self.search_space,
                seed=42 + round_idx * 100,
            )
            search_res = de_falsifier.run(search_eval, max_evaluations=self.search_budget)

            provenance.append({
                "phase": ArenaPhase.ATTACK.value,
                "strategy": search_res.strategy,
                "evaluations": search_res.evaluations_count,
                "violations_found": search_res.violations_found,
                "min_robustness": search_res.min_robustness,
            })

            if search_res.violations_found == 0 or search_res.critical_witness is None:
                # No counterexample discovered within search budget
                report = ArenaRoundReport(
                    round_index=round_idx,
                    controller_sha256=curr_ctrl.source_sha256,
                    phase=ArenaPhase.DECIDE,
                    outcome=ArenaRoundOutcome.NO_COUNTEREXAMPLE_FOUND,
                    nominal_baseline_passed=baseline_ok,
                    falsification_evaluations=search_res.evaluations_count,
                    falsification_violations=0,
                    witness_found=False,
                    summary=f"Round {round_idx}: Red team found no counterexample within {search_res.evaluations_count} evaluations.",
                    provenance_chain=provenance,
                )
                round_reports.append(report)
                break

            # 4. VERIFY: Confirm critical witness independently
            witness_scen = search_res.critical_witness.scenario
            verify_res = self.evaluator(curr_ctrl, witness_scen)
            is_valid_witness = (not verify_res.satisfied) and getattr(verify_res, "is_valid", True)

            provenance.append({
                "phase": ArenaPhase.VERIFY.value,
                "witness_verified": is_valid_witness,
                "predicate": verify_res.critical_predicate,
                "robustness": float(verify_res.min_robustness),
            })

            if not is_valid_witness:
                report = ArenaRoundReport(
                    round_index=round_idx,
                    controller_sha256=curr_ctrl.source_sha256,
                    phase=ArenaPhase.DECIDE,
                    outcome=ArenaRoundOutcome.SIMULATION_ERROR,
                    nominal_baseline_passed=baseline_ok,
                    falsification_evaluations=search_res.evaluations_count,
                    falsification_violations=search_res.violations_found,
                    witness_found=False,
                    summary=f"Round {round_idx}: Candidate witness failed reproducibility verification.",
                    provenance_chain=provenance,
                )
                round_reports.append(report)
                break

            # 5. MINIMIZE: Locally reduce the witness scenario
            min_res = self.minimizer.minimize(witness_scen, search_eval)
            reduced_scen = min_res.minimized_scenario
            self.accumulated_regressions.append(reduced_scen)

            provenance.append({
                "phase": ArenaPhase.MINIMIZE.value,
                "cost_reduction_ratio": float(min_res.cost_reduction_ratio),
                "evaluations_used": min_res.evaluations_used,
            })

            # 6. DIAGNOSE & REPAIR (Blue Team): CEGIS patch synthesis
            repair_engine = AutonomousRepairEngine(
                self.contract,
                evaluator=self.evaluator,
                inference_client=self.inference_client,
                max_revisions=self.max_repair_revisions,
            )
            repair_result = repair_engine.run_repair(
                curr_ctrl,
                reduced_scen,
                verify_res,
                candidate_generator=candidate_generator,
            )

            provenance.append({
                "phase": ArenaPhase.DIAGNOSE.value,
                "outcome": repair_result.outcome,
                "revisions_attempted": repair_result.total_revisions_attempted,
            })

            if repair_result.outcome != "REPAIRED" or repair_result.repaired_controller is None:
                report = ArenaRoundReport(
                    round_index=round_idx,
                    controller_sha256=curr_ctrl.source_sha256,
                    phase=ArenaPhase.DECIDE,
                    outcome=ArenaRoundOutcome.REVISION_REJECTED,
                    nominal_baseline_passed=baseline_ok,
                    falsification_evaluations=search_res.evaluations_count,
                    falsification_violations=search_res.violations_found,
                    witness_found=True,
                    witness_scenario=_dump_scenario(witness_scen),
                    minimized_scenario=_dump_scenario(reduced_scen),
                    cost_reduction_ratio=min_res.cost_reduction_ratio,
                    repair_attempted=True,
                    repaired_controller_sha256=None,
                    regression_passed=False,
                    holdout_passed=False,
                    summary=f"Round {round_idx}: Repair engine exhausted revisions without passing holdout gate.",
                    provenance_chain=provenance,
                )
                round_reports.append(report)
                break

            # 7. REGRESSION & HOLDOUT: Verify repaired controller against all past regressions
            repaired_candidate = repair_result.repaired_controller
            all_regressions_ok = True
            for reg in self.accumulated_regressions:
                r_check = self.evaluator(repaired_candidate, reg)
                if not r_check.satisfied or not getattr(r_check, "is_valid", True):
                    all_regressions_ok = False
                    break

            provenance.append({
                "phase": ArenaPhase.REGRESSION.value,
                "passed": all_regressions_ok,
                "accumulated_regression_suite_count": len(self.accumulated_regressions),
            })

            if not all_regressions_ok:
                report = ArenaRoundReport(
                    round_index=round_idx,
                    controller_sha256=curr_ctrl.source_sha256,
                    phase=ArenaPhase.DECIDE,
                    outcome=ArenaRoundOutcome.REVISION_REJECTED,
                    nominal_baseline_passed=baseline_ok,
                    witness_found=True,
                    witness_scenario=_dump_scenario(witness_scen),
                    minimized_scenario=_dump_scenario(reduced_scen),
                    cost_reduction_ratio=min_res.cost_reduction_ratio,
                    repair_attempted=True,
                    repaired_controller_sha256=repaired_candidate.source_sha256,
                    regression_passed=False,
                    summary=f"Round {round_idx}: Repaired controller caused a regression on historical regression suite.",
                    provenance_chain=provenance,
                )
                round_reports.append(report)
                break

            # Accept revision and advance to next co-evolution round
            last_attempt = repair_result.history[-1] if repair_result.history else None
            h_rate = last_attempt.holdout_pass_rate if last_attempt else 1.0

            round_report = ArenaRoundReport(
                round_index=round_idx,
                controller_sha256=curr_ctrl.source_sha256,
                phase=ArenaPhase.PUBLISH,
                outcome=ArenaRoundOutcome.REVISION_ACCEPTED,
                nominal_baseline_passed=baseline_ok,
                falsification_evaluations=search_res.evaluations_count,
                falsification_violations=search_res.violations_found,
                witness_found=True,
                witness_scenario=_dump_scenario(witness_scen),
                minimized_scenario=_dump_scenario(reduced_scen),
                cost_reduction_ratio=min_res.cost_reduction_ratio,
                repair_attempted=True,
                repaired_controller_sha256=repaired_candidate.source_sha256,
                regression_passed=all_regressions_ok,
                holdout_passed=True,
                holdout_pass_rate=h_rate,
                summary=f"Round {round_idx}: Successfully co-evolved controller to revision {repaired_candidate.source_sha256[:8]}.",
                provenance_chain=provenance,
            )
            round_reports.append(round_report)
            curr_ctrl = repaired_candidate

        return ArenaCampaignReport(
            campaign_id=campaign_id,
            target_altitude_m=self.contract.target_altitude_m,
            total_rounds_executed=len(round_reports),
            final_controller=curr_ctrl,
            initial_controller_sha256=initial_controller.source_sha256,
            final_controller_sha256=curr_ctrl.source_sha256 if curr_ctrl else None,
            rounds=round_reports,
            accumulated_regression_suite_size=len(self.accumulated_regressions),
            summary=(
                f"Arena co-evolution campaign completed {len(round_reports)} rounds. "
                f"Final controller: {curr_ctrl.source_sha256[:8]}."
            ),
        )

"""Counterexample-guided autonomous controller repair engine (CEGIS)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence
from domnir.contracts.stl import SafetyContract, STLRobustnessResult
from domnir.inference.vultr import VultrInferenceClient
from domnir.spec import FlightSpec, GeneratedController
from .minimize import MinimizationResult
from .search import ScenarioParameter


@dataclass(frozen=True)
class RepairAttempt:
    revision_number: int
    source_sha256: str
    passed_known_failure: bool
    passed_nominal: bool
    passed_holdout: bool
    holdout_pass_rate: float
    accepted: bool
    rejection_reason: str | None = None


@dataclass(frozen=True)
class RepairCampaignResult:
    initial_controller_sha256: str
    repaired_controller: GeneratedController | None
    total_revisions_attempted: int
    outcome: str
    history: list[RepairAttempt] = field(default_factory=list)
    summary: str = ""


class HoldoutSuite:
    """Fixed independent evaluation scenarios never disclosed to repair prompt."""

    @classmethod
    def generate_suite(cls, target_altitude_m: float = 0.10) -> list[ScenarioParameter]:
        return [
            # 1. Nominal calm hover
            ScenarioParameter(initial_altitude_m=target_altitude_m, disturbance_force_z=0.0),
            # 2. Moderate upward thermal
            ScenarioParameter(initial_altitude_m=target_altitude_m, disturbance_force_z=0.04),
            # 3. Moderate downward draft
            ScenarioParameter(initial_altitude_m=target_altitude_m, disturbance_force_z=-0.04),
            # 4. Low altitude recovery
            ScenarioParameter(initial_altitude_m=max(0.06, target_altitude_m * 0.7), disturbance_force_z=0.0),
            # 5. High altitude recovery
            ScenarioParameter(initial_altitude_m=target_altitude_m * 1.3, disturbance_force_z=0.0),
        ]


class RepairPromptBuilder:
    @staticmethod
    def build_prompt(
        contract: SafetyContract,
        original_code: str,
        witness_scenario: ScenarioParameter,
        robustness_result: STLRobustnessResult,
    ) -> str:
        return (
            "You are an expert autonomous robotics control systems engineer repairing an AI flight controller.\n\n"
            f"TARGET FLIGHT SPECIFICATION:\n"
            f"- Target Altitude: {contract.target_altitude_m:.3f} m\n"
            f"- Allowable Altitude Corridor: +/- {contract.altitude_tolerance_m:.3f} m\n"
            f"- Safety Floor: {contract.min_allowed_altitude_m:.3f} m\n"
            f"- Safety Ceiling: {contract.max_allowed_altitude_m:.3f} m\n"
            f"- Maximum Allowable Tilt: {contract.max_tilt_deg:.1f} degrees\n\n"
            f"MEASURED COUNTEREXAMPLE FAILURE (Ragnarok Witness):\n"
            f"- Initial Altitude: {witness_scenario.initial_altitude_m:.4f} m\n"
            f"- Vertical Disturbance Force: {witness_scenario.disturbance_force_z:+.4f} N\n"
            f"- Breach Predicate: {robustness_result.critical_predicate}\n"
            f"- Breach Timestamp: {robustness_result.critical_timestamp_s:.3f} s (step {robustness_result.critical_step_index})\n"
            f"- Critical Value: {robustness_result.critical_actual_value:.4f} vs threshold {robustness_result.critical_threshold:.4f}\n"
            f"- Robustness Margin: {robustness_result.min_robustness:.4f} (< 0.0 indicates critical safety violation)\n\n"
            f"ORIGINAL CONTROLLER CODE TO REPAIR:\n"
            f"```python\n{original_code}\n```\n\n"
            "MANDATORY IMPLEMENTATION RULES:\n"
            "1. Output exactly one Python code block enclosed in ```python ... ```.\n"
            "2. Define a top-level synchronous function: `def observe(observation: dict) -> list[float]:`.\n"
            "3. The returned list must contain exactly 4 floats representing motor commands in range [0.0, 1.0].\n"
            "4. Add damping or integral/feedforward correction to reject the disturbance force without overfitting.\n"
            "5. Do NOT include markdown commentary outside the code block."
        )


class AutonomousRepairEngine:
    """CEGIS controller repair loop with independent holdout verification."""

    def __init__(
        self,
        contract: SafetyContract,
        *,
        evaluator: Callable[[GeneratedController, ScenarioParameter], STLRobustnessResult],
        inference_client: VultrInferenceClient | None = None,
        max_revisions: int = 3,
    ) -> None:
        self.contract = contract
        self.evaluator = evaluator
        self.inference_client = inference_client
        self.max_revisions = max(1, max_revisions)
        self.holdout_suite = HoldoutSuite.generate_suite(contract.target_altitude_m)

    def extract_python_source(self, response_text: str) -> str:
        pattern = r"```(?:python)?\s*\n(.*?)```"
        match = re.search(pattern, response_text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Fallback to stripped text if already clean code
        return response_text.strip()

    def run_repair(
        self,
        failing_controller: GeneratedController,
        witness_scenario: ScenarioParameter,
        robustness_result: STLRobustnessResult,
        *,
        candidate_generator: Callable[[str], str] | None = None,
    ) -> RepairCampaignResult:
        history: list[RepairAttempt] = []
        initial_hash = failing_controller.source_sha256

        prompt = RepairPromptBuilder.build_prompt(
            self.contract,
            failing_controller.source_code,
            witness_scenario,
            robustness_result,
        )

        for rev in range(1, self.max_revisions + 1):
            # 1. Synthesize patch candidate
            try:
                if candidate_generator:
                    raw_patch = candidate_generator(prompt)
                elif self.inference_client:
                    raw_patch = self.inference_client.chat_completion(
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                    )
                else:
                    return RepairCampaignResult(
                        initial_controller_sha256=initial_hash,
                        repaired_controller=None,
                        total_revisions_attempted=0,
                        outcome="INFERENCE_UNAVAILABLE",
                        summary="No inference client or patch generator supplied.",
                    )

                clean_source = self.extract_python_source(raw_patch)
                candidate_ctrl = GeneratedController.from_source(
                    clean_source,
                    model_id=failing_controller.model_id,
                    prompt_version=f"repair_v{rev}",
                )
            except Exception as err:
                history.append(
                    RepairAttempt(
                        revision_number=rev,
                        source_sha256="invalid",
                        passed_known_failure=False,
                        passed_nominal=False,
                        passed_holdout=False,
                        holdout_pass_rate=0.0,
                        accepted=False,
                        rejection_reason=f"Syntax/schema validation failed: {str(err)}",
                    )
                )
                continue

            # 2. Test against known failure scenario
            known_res = self.evaluator(candidate_ctrl, witness_scenario)
            if not known_res.satisfied:
                history.append(
                    RepairAttempt(
                        revision_number=rev,
                        source_sha256=candidate_ctrl.source_sha256,
                        passed_known_failure=False,
                        passed_nominal=False,
                        passed_holdout=False,
                        holdout_pass_rate=0.0,
                        accepted=False,
                        rejection_reason=f"Failed to resolve original counterexample: {known_res.summary}",
                    )
                )
                continue

            # 3. Test against nominal hover (regression gate)
            nominal_scenario = ScenarioParameter(
                initial_altitude_m=self.contract.target_altitude_m,
                disturbance_force_z=0.0,
            )
            nom_res = self.evaluator(candidate_ctrl, nominal_scenario)
            if not nom_res.satisfied:
                history.append(
                    RepairAttempt(
                        revision_number=rev,
                        source_sha256=candidate_ctrl.source_sha256,
                        passed_known_failure=True,
                        passed_nominal=False,
                        passed_holdout=False,
                        holdout_pass_rate=0.0,
                        accepted=False,
                        rejection_reason=f"Regression on nominal hover: {nom_res.summary}",
                    )
                )
                continue

            # 4. Test against untouched holdout suite
            holdout_passes = 0
            for h_scenario in self.holdout_suite:
                h_res = self.evaluator(candidate_ctrl, h_scenario)
                if h_res.satisfied:
                    holdout_passes += 1

            pass_rate = holdout_passes / len(self.holdout_suite)
            if pass_rate < 0.80:
                history.append(
                    RepairAttempt(
                        revision_number=rev,
                        source_sha256=candidate_ctrl.source_sha256,
                        passed_known_failure=True,
                        passed_nominal=True,
                        passed_holdout=False,
                        holdout_pass_rate=pass_rate,
                        accepted=False,
                        rejection_reason=f"Holdout pass rate {pass_rate * 100:.1f}% below 80% threshold",
                    )
                )
                continue

            # 5. Success: Candidate satisfies counterexample, nominal hover, and holdout suite!
            history.append(
                RepairAttempt(
                    revision_number=rev,
                    source_sha256=candidate_ctrl.source_sha256,
                    passed_known_failure=True,
                    passed_nominal=True,
                    passed_holdout=True,
                    holdout_pass_rate=pass_rate,
                    accepted=True,
                )
            )

            summary = (
                f"Controller successfully repaired at revision {rev}. "
                f"Resolved counterexample (robustness {known_res.min_robustness:+.4f}), "
                f"passed nominal hover regression, and passed holdout suite ({holdout_passes}/{len(self.holdout_suite)})."
            )

            return RepairCampaignResult(
                initial_controller_sha256=initial_hash,
                repaired_controller=candidate_ctrl,
                total_revisions_attempted=rev,
                outcome="REPAIRED",
                history=history,
                summary=summary,
            )

        return RepairCampaignResult(
            initial_controller_sha256=initial_hash,
            repaired_controller=None,
            total_revisions_attempted=self.max_revisions,
            outcome="UNREPAIRED_WITHIN_BUDGET",
            history=history,
            summary=f"Exhausted revision budget ({self.max_revisions} attempts) without passing regression gates.",
        )

"""Unit and integration tests for Ragnarok Red/Blue Autonomous Arena."""

import pytest
from domnir.contracts.stl import SafetyContract, STLRobustnessResult
from domnir.ragnarok.arena import (
    ArenaCampaignReport,
    ArenaPhase,
    ArenaRoundOutcome,
    RedBlueArenaOrchestrator,
)
from domnir.ragnarok.search import ScenarioParameter
from domnir.spec import GeneratedController


@pytest.fixture
def arena_contract() -> SafetyContract:
    return SafetyContract(
        target_altitude_m=0.10,
        altitude_tolerance_m=0.05,
        min_allowed_altitude_m=0.05,
        max_allowed_altitude_m=1.00,
        mission_duration_s=0.20,
    )


@pytest.fixture
def initial_controller() -> GeneratedController:
    code = (
        "def observe(observation: dict) -> list[float]:\n"
        "    return [0.22, 0.22, 0.22, 0.22]\n"
    )
    return GeneratedController.from_source(code, model_id="vultr_initial")


def test_arena_campaign_resolves_counterexample_and_accepts_repair(arena_contract, initial_controller):
    # Evaluator simulates failure for weak initial controller under downward force <= -0.05
    # but passes for repaired controller containing 'kp'
    def mock_evaluator(ctrl: GeneratedController, s: ScenarioParameter) -> STLRobustnessResult:
        is_repaired = "kp" in ctrl.source_code
        if is_repaired:
            satisfied = True
            rho = 0.04
        else:
            # Fails if force <= -0.04
            satisfied = s.disturbance_force_z > -0.04
            rho = s.disturbance_force_z - (-0.04)

        return STLRobustnessResult(
            satisfied=satisfied,
            verdict="SATISFIED" if satisfied else "VIOLATED",
            min_robustness=rho,
            critical_timestamp_s=0.10,
            critical_step_index=50,
            critical_predicate="floor",
            critical_actual_value=0.04 if not satisfied else 0.10,
            critical_threshold=0.05,
            summary="Arena test evaluation",
            timeline=[],
        )

    def mock_patch_generator(prompt: str) -> str:
        return (
            "```python\n"
            "def observe(observation: dict) -> list[float]:\n"
            "    kp = 3.0\n"
            "    err = observation.get('target_altitude_m', 0.1) - observation.get('position_m', [0,0,0])[2]\n"
            "    thrust = max(0.0, min(1.0, 0.45 + kp * err))\n"
            "    return [thrust, thrust, thrust, thrust]\n"
            "```"
        )

    orchestrator = RedBlueArenaOrchestrator(
        arena_contract,
        evaluator=mock_evaluator,
        search_budget_per_round=12,
        max_repair_revisions=2,
    )

    campaign = orchestrator.run_campaign(
        initial_controller,
        max_rounds=2,
        candidate_generator=mock_patch_generator,
    )

    assert isinstance(campaign, ArenaCampaignReport)
    assert campaign.total_rounds_executed >= 1
    round1 = campaign.rounds[0]
    assert round1.witness_found is True
    assert round1.outcome == ArenaRoundOutcome.REVISION_ACCEPTED
    assert round1.regression_passed is True
    assert round1.holdout_passed is True
    assert campaign.final_controller is not None
    assert "kp" in campaign.final_controller.source_code
    assert "universal" in campaign.limitation_note.lower()


def test_arena_rejects_regression_on_historical_witnesses(arena_contract, initial_controller):
    # Evaluator where patch fixes the witness but breaks nominal calm hover
    def mock_evaluator(ctrl: GeneratedController, s: ScenarioParameter) -> STLRobustnessResult:
        is_repaired = "kp" in ctrl.source_code
        if is_repaired:
            # Fails nominal calm hover (disturbance_force_z == 0.0)
            if s.disturbance_force_z == 0.0:
                return STLRobustnessResult(
                    satisfied=False,
                    verdict="VIOLATED",
                    min_robustness=-0.05,
                    critical_timestamp_s=0.15,
                    critical_step_index=75,
                    critical_predicate="ceiling",
                    critical_actual_value=1.10,
                    critical_threshold=1.00,
                    summary="Nominal regression",
                    timeline=[],
                )
            return STLRobustnessResult(
                satisfied=True,
                verdict="SATISFIED",
                min_robustness=0.03,
                critical_timestamp_s=0.10,
                critical_step_index=50,
                critical_predicate="floor",
                critical_actual_value=0.10,
                critical_threshold=0.05,
                summary="Witness satisfied",
                timeline=[],
            )

        satisfied = s.disturbance_force_z > -0.04
        return STLRobustnessResult(
            satisfied=satisfied,
            verdict="SATISFIED" if satisfied else "VIOLATED",
            min_robustness=s.disturbance_force_z - (-0.04),
            critical_timestamp_s=0.10,
            critical_step_index=50,
            critical_predicate="floor",
            critical_actual_value=0.04 if not satisfied else 0.10,
            critical_threshold=0.05,
            summary="Original eval",
            timeline=[],
        )

    def mock_patch_generator(prompt: str) -> str:
        return (
            "```python\n"
            "def observe(observation: dict) -> list[float]:\n"
            "    kp = 3.0\n"
            "    return [0.99, 0.99, 0.99, 0.99]\n"
            "```"
        )

    orchestrator = RedBlueArenaOrchestrator(
        arena_contract,
        evaluator=mock_evaluator,
        search_budget_per_round=10,
    )

    campaign = orchestrator.run_campaign(
        initial_controller,
        max_rounds=1,
        candidate_generator=mock_patch_generator,
    )

    assert campaign.rounds[0].outcome == ArenaRoundOutcome.REVISION_REJECTED


def test_arena_provenance_chain_integrity(arena_contract, initial_controller):
    def mock_evaluator(ctrl: GeneratedController, s: ScenarioParameter) -> STLRobustnessResult:
        return STLRobustnessResult(
            satisfied=True,
            verdict="SATISFIED",
            min_robustness=0.05,
            critical_timestamp_s=0.10,
            critical_step_index=50,
            critical_predicate="tracking",
            critical_actual_value=0.10,
            critical_threshold=0.05,
            summary="Calm",
            timeline=[],
        )

    orchestrator = RedBlueArenaOrchestrator(
        arena_contract,
        evaluator=mock_evaluator,
        search_budget_per_round=5,
    )

    campaign = orchestrator.run_campaign(initial_controller, max_rounds=1)
    round_rep = campaign.rounds[0]
    phases = [entry["phase"] for entry in round_rep.provenance_chain]
    assert ArenaPhase.SPECIFY.value in phases
    assert ArenaPhase.BASELINE.value in phases
    assert ArenaPhase.ATTACK.value in phases
    assert round_rep.outcome == ArenaRoundOutcome.NO_COUNTEREXAMPLE_FOUND

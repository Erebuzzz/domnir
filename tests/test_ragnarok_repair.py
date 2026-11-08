"""Unit tests for Counterexample-Guided Autonomous Controller Repair."""

import pytest
from domnir.contracts.stl import SafetyContract, STLRobustnessResult
from domnir.ragnarok.repair import (
    AutonomousRepairEngine,
    HoldoutSuite,
    RepairPromptBuilder,
)
from domnir.ragnarok.search import ScenarioParameter
from domnir.spec import GeneratedController


@pytest.fixture
def base_contract() -> SafetyContract:
    return SafetyContract(
        target_altitude_m=0.10,
        altitude_tolerance_m=0.05,
        min_allowed_altitude_m=0.05,
        max_allowed_altitude_m=1.00,
    )


@pytest.fixture
def weak_controller() -> GeneratedController:
    code = (
        "def observe(observation: dict) -> list[float]:\n"
        "    return [0.2, 0.2, 0.2, 0.2]\n"
    )
    return GeneratedController.from_source(code, model_id="test_model")


def test_repair_prompt_contains_witness_and_no_holdouts(base_contract, weak_controller):
    witness = ScenarioParameter(initial_altitude_m=0.08, disturbance_force_z=-0.06)
    mock_res = STLRobustnessResult(
        satisfied=False,
        verdict="VIOLATED",
        min_robustness=-0.02,
        critical_timestamp_s=0.15,
        critical_step_index=75,
        critical_predicate="floor",
        critical_actual_value=0.03,
        critical_threshold=0.05,
        summary="Floor violation",
        timeline=[],
    )
    prompt = RepairPromptBuilder.build_prompt(base_contract, weak_controller.source_code, witness, mock_res)

    assert "MEASURED COUNTEREXAMPLE FAILURE" in prompt
    assert "-0.0600" in prompt
    assert "critical safety violation" in prompt
    # Ensure hidden holdout parameters are NOT leaked into the prompt!
    assert "Holdout" not in prompt


def test_repair_accepts_valid_patch_passing_all_gates(base_contract, weak_controller):
    witness = ScenarioParameter(initial_altitude_m=0.08, disturbance_force_z=-0.06)
    mock_res = STLRobustnessResult(
        satisfied=False,
        verdict="VIOLATED",
        min_robustness=-0.02,
        critical_timestamp_s=0.15,
        critical_step_index=75,
        critical_predicate="floor",
        critical_actual_value=0.03,
        critical_threshold=0.05,
        summary="Floor breach",
        timeline=[],
    )

    # Mock evaluator that passes for patched controller
    def mock_evaluator(ctrl: GeneratedController, s: ScenarioParameter) -> STLRobustnessResult:
        is_patched = "kp" in ctrl.source_code
        # Patched controller passes all scenarios
        satisfied = is_patched or (s.disturbance_force_z >= 0.0)
        return STLRobustnessResult(
            satisfied=satisfied,
            verdict="SATISFIED" if satisfied else "VIOLATED",
            min_robustness=0.03 if satisfied else -0.02,
            critical_timestamp_s=0.20,
            critical_step_index=100,
            critical_predicate="floor",
            critical_actual_value=0.10 if satisfied else 0.03,
            critical_threshold=0.05,
            summary="Test eval",
            timeline=[],
        )

    # Generator returns a valid PID-style controller with kp
    def mock_patch_generator(prompt: str) -> str:
        return (
            "```python\n"
            "def observe(observation: dict) -> list[float]:\n"
            "    kp = 2.5\n"
            "    err = observation.get('target_altitude_m', 0.1) - observation.get('position_m', [0,0,0])[2]\n"
            "    thrust = max(0.0, min(1.0, 0.45 + kp * err))\n"
            "    return [thrust, thrust, thrust, thrust]\n"
            "```"
        )

    engine = AutonomousRepairEngine(base_contract, evaluator=mock_evaluator, max_revisions=2)
    res = engine.run_repair(weak_controller, witness, mock_res, candidate_generator=mock_patch_generator)

    assert res.outcome == "REPAIRED"
    assert res.repaired_controller is not None
    assert res.total_revisions_attempted == 1
    assert res.history[0].accepted is True
    assert res.history[0].passed_holdout is True


def test_repair_rejects_nominal_regression(base_contract, weak_controller):
    witness = ScenarioParameter(initial_altitude_m=0.08, disturbance_force_z=-0.06)
    mock_res = STLRobustnessResult(
        satisfied=False,
        verdict="VIOLATED",
        min_robustness=-0.02,
        critical_timestamp_s=0.15,
        critical_step_index=75,
        critical_predicate="floor",
        critical_actual_value=0.03,
        critical_threshold=0.05,
        summary="Floor breach",
        timeline=[],
    )

    # Evaluator simulates a candidate that overfits to negative disturbance but causes regression on calm hover
    def mock_evaluator(ctrl: GeneratedController, s: ScenarioParameter) -> STLRobustnessResult:
        if s.disturbance_force_z == 0.0:
            # Fails nominal hover due to overthrusting into ceiling
            return STLRobustnessResult(
                satisfied=False,
                verdict="VIOLATED",
                min_robustness=-0.05,
                critical_timestamp_s=0.25,
                critical_step_index=125,
                critical_predicate="ceiling",
                critical_actual_value=1.15,
                critical_threshold=1.00,
                summary="Ceiling breach on nominal",
                timeline=[],
            )
        return STLRobustnessResult(
            satisfied=True,
            verdict="SATISFIED",
            min_robustness=0.02,
            critical_timestamp_s=0.20,
            critical_step_index=100,
            critical_predicate="floor",
            critical_actual_value=0.09,
            critical_threshold=0.05,
            summary="Fixed counterexample",
            timeline=[],
        )

    def mock_patch_generator(prompt: str) -> str:
        return (
            "```python\n"
            "def observe(observation: dict) -> list[float]:\n"
            "    # Overthrusting constant\n"
            "    return [0.95, 0.95, 0.95, 0.95]\n"
            "```"
        )

    engine = AutonomousRepairEngine(base_contract, evaluator=mock_evaluator, max_revisions=1)
    res = engine.run_repair(weak_controller, witness, mock_res, candidate_generator=mock_patch_generator)

    assert res.outcome == "UNREPAIRED_WITHIN_BUDGET"
    assert res.repaired_controller is None
    assert "Regression on nominal hover" in res.history[0].rejection_reason


def test_repair_extracts_source_from_inference_response_object(base_contract, weak_controller):
    from unittest.mock import MagicMock
    from domnir.inference.vultr import InferenceResponse

    witness = ScenarioParameter(initial_altitude_m=0.08, disturbance_force_z=-0.06)
    mock_res = STLRobustnessResult(
        satisfied=False,
        verdict="VIOLATED",
        min_robustness=-0.02,
        critical_timestamp_s=0.15,
        critical_step_index=75,
        critical_predicate="floor",
        critical_actual_value=0.03,
        critical_threshold=0.05,
        summary="Floor breach",
        timeline=[],
    )

    mock_client = MagicMock()
    mock_client.chat_completion.return_value = InferenceResponse(
        content="```python\ndef observe(observation: dict) -> list[float]:\n    kp = 2.0\n    return [0.26, 0.26, 0.26, 0.26]\n```",
        model="meta/llama-3.3-70b-instruct",
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        finish_reason="stop",
    )

    def mock_evaluator(ctrl: GeneratedController, s: ScenarioParameter) -> STLRobustnessResult:
        return STLRobustnessResult(
            satisfied=True,
            verdict="SATISFIED",
            min_robustness=0.02,
            critical_timestamp_s=0.20,
            critical_step_index=100,
            critical_predicate="ceiling",
            critical_actual_value=0.11,
            critical_threshold=1.00,
            summary="Pass",
            timeline=[],
        )

    engine = AutonomousRepairEngine(
        base_contract,
        evaluator=mock_evaluator,
        inference_client=mock_client,
        max_revisions=1,
    )
    res = engine.run_repair(weak_controller, witness, mock_res)
    assert res.outcome == "REPAIRED"
    assert res.repaired_controller is not None
    assert "kp = 2.0" in res.repaired_controller.source_code

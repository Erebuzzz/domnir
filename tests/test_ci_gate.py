"""Tests for Robotics Continuous Integration (CI) and Revision Regression Gate."""

from __future__ import annotations

import pytest

from domnir.ci.gate import ReleaseAssessment, ReleaseStatus, RoboticsCIGate
from domnir.contracts.stl import SafetyContract, STLRobustnessResult
from domnir.ragnarok.search import ScenarioParameter
from domnir.spec import GeneratedController


@pytest.fixture
def base_contract() -> SafetyContract:
    return SafetyContract(
        target_altitude_m=0.10,
        altitude_tolerance_m=0.05,
        min_allowed_altitude_m=0.05,
        max_allowed_altitude_m=1.00,
        mission_duration_s=0.20,
    )


@pytest.fixture
def mock_scenarios() -> list[ScenarioParameter]:
    return [
        ScenarioParameter(initial_altitude_m=0.10, disturbance_force_z=0.0),
        ScenarioParameter(initial_altitude_m=0.10, disturbance_force_z=0.04),
        ScenarioParameter(initial_altitude_m=0.10, disturbance_force_z=-0.04),
        ScenarioParameter(initial_altitude_m=0.07, disturbance_force_z=0.0),
        ScenarioParameter(initial_altitude_m=0.13, disturbance_force_z=0.0),
    ]


def test_clean_revision_approval(base_contract, mock_scenarios):
    """Candidate passes all scenarios with 0 regressions, achieving RELEASE_APPROVED."""

    def mock_eval(ctrl, scenario):
        return STLRobustnessResult(
            satisfied=True,
            verdict="SATISFIED",
            min_robustness=0.04,
            critical_timestamp_s=0.10,
            critical_step_index=50,
            critical_predicate="floor",
            critical_actual_value=0.09,
            critical_threshold=0.05,
            summary="All satisfied",
        )

    gate = RoboticsCIGate(evaluator=mock_eval, min_pass_rate_for_approval=0.80)
    assessment = gate.evaluate_revision(
        candidate_ctrl="candidate_code_v2",
        baseline_ctrl="baseline_code_v1",
        contract=base_contract,
        suite=mock_scenarios,
    )

    assert assessment.status == ReleaseStatus.RELEASE_APPROVED
    assert assessment.regressions_count == 0
    assert len(assessment.new_failures) == 0
    assert assessment.contracts_passed == 5
    assert assessment.contracts_evaluated == 5
    assert assessment.candidate_pass_rate == 1.0
    assert assessment.min_robustness_margin == 0.04
    assert len(assessment.court_record_hashes) == 5
    assert "Release approved" in assessment.summary


def test_regression_blocking_when_candidate_breaks_scenario(base_contract, mock_scenarios):
    """Candidate fails scenario 2 where baseline passed, blocking release with REGRESSION_FOUND."""

    def mock_eval(ctrl, scenario):
        is_candidate = "cand" in str(ctrl)
        is_failing_scenario = scenario.disturbance_force_z == -0.04
        satisfied = not (is_candidate and is_failing_scenario)

        return STLRobustnessResult(
            satisfied=satisfied,
            verdict="SATISFIED" if satisfied else "VIOLATED",
            min_robustness=0.03 if satisfied else -0.02,
            critical_timestamp_s=0.12,
            critical_step_index=60,
            critical_predicate="floor",
            critical_actual_value=0.08 if satisfied else 0.03,
            critical_threshold=0.05,
            summary="Eval result",
        )

    gate = RoboticsCIGate(evaluator=mock_eval)
    assessment = gate.evaluate_revision(
        candidate_ctrl="cand_v2",
        baseline_ctrl="baseline_v1",
        contract=base_contract,
        suite=mock_scenarios,
    )

    assert assessment.status == ReleaseStatus.REGRESSION_FOUND
    assert assessment.regressions_count == 1
    assert len(assessment.new_failures) == 1
    assert "scenario_2" in assessment.new_failures[0]
    assert assessment.contracts_passed == 4
    assert "Release blocked" in assessment.summary
    assert "regression" in assessment.summary.lower()


def test_resolved_failure_tracking(base_contract, mock_scenarios):
    """Candidate fixes a scenario where baseline previously failed."""

    def mock_eval(ctrl, scenario):
        is_candidate = "cand" in str(ctrl)
        is_hard_scenario = scenario.disturbance_force_z == 0.04
        if is_hard_scenario:
            satisfied = is_candidate
        else:
            satisfied = True

        return STLRobustnessResult(
            satisfied=satisfied,
            verdict="SATISFIED" if satisfied else "VIOLATED",
            min_robustness=0.02 if satisfied else -0.01,
            critical_timestamp_s=0.15,
            critical_step_index=75,
            critical_predicate="ceiling",
            critical_actual_value=0.12 if satisfied else 1.05,
            critical_threshold=1.00,
            summary="Eval result",
        )

    gate = RoboticsCIGate(evaluator=mock_eval)
    assessment = gate.evaluate_revision(
        candidate_ctrl="cand_v2",
        baseline_ctrl="baseline_v1",
        contract=base_contract,
        suite=mock_scenarios,
    )

    assert assessment.status == ReleaseStatus.RELEASE_APPROVED
    assert assessment.regressions_count == 0
    assert len(assessment.resolved_failures) == 1
    assert "scenario_1" in assessment.resolved_failures[0]


def test_awaiting_review_when_pass_rate_below_threshold(base_contract, mock_scenarios):
    """Candidate has 0 regressions but pass rate is 60% (< 80%), leading to AWAITING_REVIEW."""

    def mock_eval(ctrl, scenario):
        # Both candidate and baseline fail on scenarios with non-zero disturbance
        satisfied = scenario.disturbance_force_z == 0.0
        return STLRobustnessResult(
            satisfied=satisfied,
            verdict="SATISFIED" if satisfied else "VIOLATED",
            min_robustness=0.03 if satisfied else -0.05,
            critical_timestamp_s=0.10,
            critical_step_index=50,
            critical_predicate="floor",
            critical_actual_value=0.08 if satisfied else 0.02,
            critical_threshold=0.05,
            summary="Eval result",
        )

    gate = RoboticsCIGate(evaluator=mock_eval, min_pass_rate_for_approval=0.80)
    assessment = gate.evaluate_revision(
        candidate_ctrl="cand_v2",
        baseline_ctrl="baseline_v1",
        contract=base_contract,
        suite=mock_scenarios,
    )

    assert assessment.status == ReleaseStatus.AWAITING_REVIEW
    assert assessment.regressions_count == 0
    assert assessment.contracts_passed == 3
    assert assessment.contracts_evaluated == 5
    assert assessment.candidate_pass_rate == 0.60
    assert "Release awaiting review" in assessment.summary


def test_blocked_incomplete_on_empty_suite(base_contract):
    """Empty scenario suite blocks release with BLOCKED_INCOMPLETE."""
    gate = RoboticsCIGate()
    assessment = gate.evaluate_revision(
        candidate_ctrl="cand_v2",
        baseline_ctrl="baseline_v1",
        contract=base_contract,
        suite=[],
    )

    assert assessment.status == ReleaseStatus.BLOCKED_INCOMPLETE
    assert assessment.contracts_evaluated == 0
    assert "Evaluation blocked" in assessment.summary


def test_blocked_incomplete_on_evaluator_runtime_crash(base_contract, mock_scenarios):
    """Runtime error in candidate evaluation marks status as BLOCKED_INCOMPLETE."""

    def crashing_eval(ctrl, scenario):
        if "cand" in str(ctrl) and scenario.disturbance_force_z != 0.0:
            raise RuntimeError("Fatal hardware simulation crash")
        return STLRobustnessResult(
            satisfied=True,
            verdict="SATISFIED",
            min_robustness=0.02,
            critical_timestamp_s=0.0,
            critical_step_index=0,
            critical_predicate="floor",
            critical_actual_value=0.1,
            critical_threshold=0.05,
            summary="Pass",
        )

    gate = RoboticsCIGate(evaluator=crashing_eval)
    assessment = gate.evaluate_revision(
        candidate_ctrl="cand_v2",
        baseline_ctrl="baseline_v1",
        contract=base_contract,
        suite=mock_scenarios,
    )

    assert assessment.status == ReleaseStatus.BLOCKED_INCOMPLETE
    assert "incomplete" in assessment.summary.lower()


def test_strictly_no_unqualified_safe_status():
    """Verify that no unqualified SAFE status exists in ReleaseStatus or is accepted by ReleaseAssessment."""
    allowed_statuses = {s.value for s in ReleaseStatus}
    assert "SAFE" not in allowed_statuses
    assert "PROVEN_SAFE" not in allowed_statuses
    assert allowed_statuses == {
        "RELEASE_APPROVED",
        "REGRESSION_FOUND",
        "BLOCKED_INCOMPLETE",
        "AWAITING_REVIEW",
    }

    # Attempting to assign prohibited unqualified claim in summary raises ValueError
    with pytest.raises(ValueError, match="prohibited unqualified safety claim"):
        ReleaseAssessment(
            status=ReleaseStatus.RELEASE_APPROVED,
            candidate_version="v2",
            baseline_version="v1",
            contracts_evaluated=5,
            contracts_passed=5,
            regressions_count=0,
            summary="Candidate controller is proven safe for all hardware conditions.",
        )


def test_revision_evaluation_with_real_mujoco_simulation(base_contract):
    """End to end test using default MuJoCo simulation without custom evaluator."""
    code_ctrl = (
        "def observe(observation: dict) -> list[float]:\n"
        "    z = observation['position_m'][2]\n"
        "    vz = observation['velocity_mps'][2]\n"
        "    thrust = max(0.0, min(0.35, 0.26487 + 0.15 * (0.1 - z) - 0.08 * vz))\n"
        "    return [thrust, 0.0, 0.0, 0.0]\n"
    )
    ctrl_cand = GeneratedController.from_source(code_ctrl, model_id="candidate_model")
    ctrl_base = GeneratedController.from_source(code_ctrl, model_id="baseline_model")

    small_suite = [
        ScenarioParameter(initial_altitude_m=0.10, disturbance_force_z=0.0),
        ScenarioParameter(initial_altitude_m=0.10, disturbance_force_z=0.02),
    ]

    gate = RoboticsCIGate(min_pass_rate_for_approval=0.50)
    assessment = gate.evaluate_revision(
        candidate_ctrl=ctrl_cand,
        baseline_ctrl=ctrl_base,
        contract=base_contract,
        suite=small_suite,
    )

    assert assessment.contracts_evaluated == 2
    assert assessment.regressions_count == 0
    assert assessment.candidate_version == ctrl_cand.source_sha256[:12]
    assert assessment.baseline_version == ctrl_base.source_sha256[:12]
    assert assessment.status in (ReleaseStatus.RELEASE_APPROVED, ReleaseStatus.AWAITING_REVIEW)
    assert len(assessment.court_record_hashes) == 2

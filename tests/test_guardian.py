"""Unit tests for Guardian runtime safety supervisor and action shielding."""

import math
from pathlib import Path
import pytest

from domnir.contracts.stl import SafetyContract
from domnir.guardian import (
    FeasibilityStatus,
    GuardianSupervisor,
    GuardianTrialComparator,
    GuardianTrialReport,
    InterventionCause,
    InterventionRecord,
)


@pytest.fixture
def nominal_contract() -> SafetyContract:
    return SafetyContract(
        target_altitude_m=0.10,
        altitude_tolerance_m=0.08,
        min_allowed_altitude_m=0.05,
        max_allowed_altitude_m=0.30,
        settling_time_s=0.15,
        mission_duration_s=0.20,
    )


def test_zero_intervention_on_nominal_safe_hover(nominal_contract: SafetyContract):
    comparator = GuardianTrialComparator(nominal_contract)

    def hover_controller(observation: dict) -> list[float]:
        z = observation["position_m"][2]
        vz = observation["velocity_mps"][2]
        # Linear altitude PD around hover thrust 0.26487 N
        thrust = max(0.0, min(0.35, 0.26487 + 0.15 * (0.10 - z) - 0.08 * vz))
        return [thrust, 0.0, 0.0, 0.0]

    report = comparator.compare(hover_controller)

    assert report.interventions_count == 0
    assert len(report.interventions_timeline) == 0
    assert report.infeasible_interventions_count == 0
    assert report.unshielded_verdict == "SATISFIED"
    assert report.shielded_verdict == "SATISFIED"
    assert report.unshielded_robustness > 0.0
    assert report.shielded_robustness > 0.0
    assert report.shielded_satisfied is True
    assert report.unshielded_satisfied is True


def test_floor_shield_on_zero_thrust_dive_prevents_crash(nominal_contract: SafetyContract):
    comparator = GuardianTrialComparator(nominal_contract)

    def zero_thrust_dive(observation: dict) -> list[float]:
        return [0.0, 0.0, 0.0, 0.0]

    report = comparator.compare(zero_thrust_dive, {"initial_altitude_m": 0.15})

    # Original controller alone must remain flagged as violated
    assert report.unshielded_verdict == "VIOLATED"
    assert report.unshielded_robustness < 0.0
    assert report.unshielded_satisfied is False

    # Guardian must intervene and prevent ground crash
    assert report.interventions_count > 0
    assert report.shielded_verdict == "GUARDIAN_INTERVENED"
    assert report.shielded_robustness > 0.0
    assert report.shielded_satisfied is True

    # Validate first logged intervention
    first_record = report.interventions_timeline[0]
    assert first_record.cause == InterventionCause.FLOOR_BREACH
    assert first_record.feasibility == FeasibilityStatus.FEASIBLE
    assert first_record.requested_action[0] == 0.0
    assert first_record.applied_action[0] == 0.35
    assert "Floor breach predicted" in first_record.reason


def test_ceiling_shield_on_runaway_climb_cuts_thrust():
    contract = SafetyContract(
        target_altitude_m=0.10,
        altitude_tolerance_m=0.12,
        min_allowed_altitude_m=0.05,
        max_allowed_altitude_m=0.20,
        settling_time_s=0.35,
        mission_duration_s=0.40,
    )
    comparator = GuardianTrialComparator(contract)

    def runaway_controller(observation: dict) -> list[float]:
        return [0.35, 0.0, 0.0, 0.0]

    report = comparator.compare(runaway_controller, {"initial_altitude_m": 0.12})

    # Controller unshielded run breaches ceiling
    assert report.unshielded_verdict == "VIOLATED"
    assert report.unshielded_robustness < 0.0

    # Shielded flight stays within bounds
    assert report.interventions_count > 0
    assert report.shielded_verdict == "GUARDIAN_INTERVENED"
    assert report.shielded_robustness > 0.0

    # Verify at least one ceiling intervention cutting thrust to idle
    ceiling_records = [
        rec for rec in report.interventions_timeline
        if rec.cause == InterventionCause.CEILING_BREACH
    ]
    assert len(ceiling_records) > 0
    for rec in ceiling_records:
        assert rec.applied_action[0] == 0.0
        assert "Ceiling breach predicted" in rec.reason


def test_infeasible_stopping_distance_detection():
    supervisor = GuardianSupervisor(
        min_allowed_altitude_m=0.05,
        altitude_margin_m=0.02,
        mass_kg=0.027,
        max_thrust_n=0.35,
    )

    # Drone at z=0.06m moving down at -1.5 m/s
    # Stopping distance is ~0.357m, while available clearance is only 0.01m
    obs = {
        "position_m": [0.0, 0.0, 0.06],
        "velocity_mps": [0.0, 0.0, -1.5],
        "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
        "sim_time_s": 0.10,
        "dt_s": 0.002,
    }
    action, record = supervisor.inspect_and_shield(obs, [0.0, 0.0, 0.0, 0.0], step_index=50)

    assert record is not None
    assert record.cause == InterventionCause.FLOOR_BREACH
    assert record.feasibility == FeasibilityStatus.INFEASIBLE_INERTIA
    assert "exceeds available altitude" in record.reason
    assert action[0] == 0.35


def test_infeasible_saturated_thrust_detection():
    # If plant mass is too large for max thrust, max upward acceleration is negative
    supervisor = GuardianSupervisor(
        min_allowed_altitude_m=0.05,
        mass_kg=0.50,
        max_thrust_n=0.35,
    )
    obs = {
        "position_m": [0.0, 0.0, 0.06],
        "velocity_mps": [0.0, 0.0, 0.0],
        "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
        "sim_time_s": 0.05,
        "dt_s": 0.002,
    }
    action, record = supervisor.inspect_and_shield(obs, [0.0, 0.0, 0.0, 0.0], step_index=25)

    assert record is not None
    assert record.cause == InterventionCause.FLOOR_BREACH
    assert record.feasibility == FeasibilityStatus.INFEASIBLE_SATURATED
    assert "cannot overcome gravity" in record.reason


def test_attitude_shield_levels_differential_commands():
    supervisor = GuardianSupervisor(max_tilt_deg=45.0, tilt_margin_deg=5.0)

    # Construct quaternion with 42 deg pitch tilt (exceeds 40 deg threshold)
    half_pitch = math.radians(21.0)
    quat = [math.cos(half_pitch), 0.0, math.sin(half_pitch), 0.0]

    obs = {
        "position_m": [0.0, 0.0, 0.10],
        "velocity_mps": [0.0, 0.0, 0.0],
        "orientation_quat_wxyz": quat,
        "sim_time_s": 0.04,
        "dt_s": 0.002,
    }
    req_action = [0.26487, 0.40, -0.20, 0.10]
    action, record = supervisor.inspect_and_shield(obs, req_action, step_index=20)

    assert record is not None
    assert record.cause == InterventionCause.TILT_EXCESS
    assert record.feasibility == FeasibilityStatus.FEASIBLE
    assert action == [0.26487, 0.0, 0.0, 0.0]


def test_deterministic_replay_of_intervention_records(nominal_contract: SafetyContract):
    comparator = GuardianTrialComparator(nominal_contract)

    def erratic_controller(obs: dict) -> list[float]:
        # Alternates between zero thrust and dive
        step = obs.get("step_index", 0)
        return [0.0, 0.0, 0.0, 0.0] if (step % 2 == 0) else [0.10, 0.0, 0.0, 0.0]

    report1 = comparator.compare(erratic_controller, {"initial_altitude_m": 0.14})
    report2 = comparator.compare(erratic_controller, {"initial_altitude_m": 0.14})

    assert report1.interventions_count == report2.interventions_count
    assert math.isclose(report1.shielded_robustness, report2.shielded_robustness, abs_tol=1e-9)
    assert math.isclose(report1.unshielded_robustness, report2.unshielded_robustness, abs_tol=1e-9)
    assert report1.shielded_verdict == report2.shielded_verdict
    assert report1.unshielded_verdict == report2.unshielded_verdict

    for r1, r2 in zip(report1.interventions_timeline, report2.interventions_timeline, strict=True):
        assert r1.step_index == r2.step_index
        assert math.isclose(r1.timestamp_s, r2.timestamp_s, abs_tol=1e-9)
        assert r1.requested_action == r2.requested_action
        assert r1.applied_action == r2.applied_action
        assert r1.cause == r2.cause
        assert r1.feasibility == r2.feasibility
        assert r1.predicted_state == r2.predicted_state
        assert r1.reason == r2.reason


def test_action_formats_handling():
    supervisor = GuardianSupervisor()
    obs = {
        "position_m": [0.0, 0.0, 0.10],
        "velocity_mps": [0.0, 0.0, 0.0],
        "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
        "sim_time_s": 0.01,
        "dt_s": 0.002,
    }

    # Dict format
    dict_act = {"thrust": 0.26487, "moment_x": 0.0, "moment_y": 0.0, "moment_z": 0.0}
    applied, rec = supervisor.inspect_and_shield(obs, dict_act, step_index=5)
    assert rec is None
    assert applied == [0.26487, 0.0, 0.0, 0.0]

    # 4 rotor commands format
    rotor_act = [0.066, 0.066, 0.066, 0.066]
    applied, rec = supervisor.inspect_and_shield(obs, rotor_act, step_index=5)
    assert rec is None
    assert applied == [0.066, 0.066, 0.066, 0.066]


def test_guardian_pydantic_serialization():
    rec = InterventionRecord(
        step_index=10,
        timestamp_s=0.02,
        requested_action=[0.0, 0.0, 0.0, 0.0],
        applied_action=[0.35, 0.0, 0.0, 0.0],
        cause=InterventionCause.FLOOR_BREACH,
        feasibility=FeasibilityStatus.FEASIBLE,
        predicted_state={"altitude_m": 0.04},
        reason="Floor breach predicted",
    )
    raw = rec.model_dump_json()
    loaded = InterventionRecord.model_validate_json(raw)
    assert loaded.cause == InterventionCause.FLOOR_BREACH
    assert loaded.applied_action[0] == 0.35

    report = GuardianTrialReport(
        unshielded_robustness=-0.05,
        unshielded_verdict="VIOLATED",
        shielded_robustness=0.02,
        shielded_verdict="GUARDIAN_INTERVENED",
        interventions_count=1,
        interventions_timeline=[rec],
        infeasible_interventions_count=0,
        summary="Test report",
    )
    rep_raw = report.model_dump_json()
    rep_loaded = GuardianTrialReport.model_validate_json(rep_raw)
    assert rep_loaded.shielded_verdict == "GUARDIAN_INTERVENED"
    assert rep_loaded.interventions_timeline[0].step_index == 10


def test_zero_em_dashes_in_guardian_codebase():
    """Verify strictly zero em dashes and en dashes in guardian module and tests."""
    repo_root = Path(__file__).resolve().parents[1]
    paths = [
        repo_root / "domnir" / "guardian" / "__init__.py",
        repo_root / "domnir" / "guardian" / "supervisor.py",
        repo_root / "tests" / "test_guardian.py",
    ]
    mdash_entity = "&" + "mdash;"
    for p in paths:
        assert p.is_file(), f"File {p} does not exist"
        text = p.read_text(encoding="utf-8")
        assert "\u2014" not in text, f"Em dash (\\u2014) detected in {p}"
        assert "\u2013" not in text, f"En dash (\\u2013) detected in {p}"
        if p != Path(__file__):
            assert mdash_entity not in text, f"HTML mdash detected in {p}"

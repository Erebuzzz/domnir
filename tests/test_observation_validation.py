"""Tests for observation-frame validation (Audit Item P2-H).

Validates that observation frames delivered to flight controllers (both baseline
and guest) are strictly checked for required fields, finite values, proper vector
dimensions, unit quaternion, dt consistency, and monotonic step/time alignment.
A malformed observation frame is a server bug, so it must fail with an HTTP 500
class error and never emit a verdict or court record.
"""

import copy
import math
import pytest
from fastapi.testclient import TestClient

from domnir.api.app import app
from domnir.faults.injector import FaultInjector
from domnir.faults.schema import MissionFaultSchedule, SensorFaultSchedule
from domnir.missions.simulator import (
    MalformedObservationError,
    validate_observation_frame,
)

client = TestClient(app)


def _make_valid_obs():
    return {
        "schema_version": "1.0",
        "trial_id": "mission-test-trial",
        "step_index": 10,
        "sim_time_s": 0.02,
        "dt_s": 0.01,
        "position_m": [0.0, 0.0, 0.5],
        "velocity_mps": [0.1, 0.0, -0.05],
        "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
        "body_angular_velocity_rps": [0.0, 0.0, 0.0],
        "target_position_m": [0.0, 0.0, 1.0],
        "target_velocity_mps": [0.0, 0.0, 0.0],
        "target_yaw_rad": 0.0,
        "active_stage_id": "climb",
        "stage_kind": "waypoint",
    }


def test_valid_observation_passes():
    obs = _make_valid_obs()
    validate_observation_frame(
        obs,
        expected_controller_dt_s=0.01,
        physics_dt_s=0.002,
        current_step_index=10,
    )


@pytest.mark.parametrize(
    "missing_key",
    [
        "schema_version",
        "trial_id",
        "step_index",
        "sim_time_s",
        "dt_s",
        "position_m",
        "velocity_mps",
        "orientation_quat_wxyz",
        "body_angular_velocity_rps",
        "target_position_m",
        "target_velocity_mps",
        "target_yaw_rad",
        "active_stage_id",
        "stage_kind",
    ],
)
def test_missing_required_field_raises(missing_key):
    obs = _make_valid_obs()
    obs.pop(missing_key)
    with pytest.raises(MalformedObservationError, match=f"Missing required observation field: {missing_key}"):
        validate_observation_frame(obs)


def test_invalid_schema_version_raises():
    obs = _make_valid_obs()
    obs["schema_version"] = "2.0"
    with pytest.raises(MalformedObservationError, match="Invalid observation schema_version"):
        validate_observation_frame(obs)


def test_empty_or_non_string_trial_id_raises():
    obs = _make_valid_obs()
    obs["trial_id"] = "   "
    with pytest.raises(MalformedObservationError, match="trial_id must be a non-empty string"):
        validate_observation_frame(obs)


@pytest.mark.parametrize("invalid_step", [-1, 2.5, "10", True])
def test_invalid_step_index_raises(invalid_step):
    obs = _make_valid_obs()
    obs["step_index"] = invalid_step
    with pytest.raises(MalformedObservationError, match="step_index must be a non-negative integer"):
        validate_observation_frame(obs)


def test_step_index_exceeding_current_step_raises():
    obs = _make_valid_obs()
    obs["step_index"] = 20
    with pytest.raises(MalformedObservationError, match="exceeds current step"):
        validate_observation_frame(obs, current_step_index=10)


@pytest.mark.parametrize("invalid_time", [float("nan"), float("inf"), -0.01, "0.02"])
def test_non_finite_or_negative_sim_time_raises(invalid_time):
    obs = _make_valid_obs()
    obs["sim_time_s"] = invalid_time
    with pytest.raises(MalformedObservationError, match="sim_time_s must be a finite non-negative float"):
        validate_observation_frame(obs)


def test_sim_time_inconsistent_with_physics_step_raises():
    obs = _make_valid_obs()
    obs["step_index"] = 10
    obs["sim_time_s"] = 0.05  # expected 10 * 0.002 = 0.02
    with pytest.raises(MalformedObservationError, match="inconsistent with step_index"):
        validate_observation_frame(obs, physics_dt_s=0.002)


@pytest.mark.parametrize("invalid_dt", [float("nan"), float("inf"), 0.0, -0.01, "0.01"])
def test_non_finite_or_non_positive_dt_raises(invalid_dt):
    obs = _make_valid_obs()
    obs["dt_s"] = invalid_dt
    with pytest.raises(MalformedObservationError, match="dt_s must be a positive finite float"):
        validate_observation_frame(obs)


def test_dt_mismatch_with_expected_controller_dt_raises():
    obs = _make_valid_obs()
    obs["dt_s"] = 0.02
    with pytest.raises(MalformedObservationError, match="does not match expected controller_dt_s"):
        validate_observation_frame(obs, expected_controller_dt_s=0.01)


@pytest.mark.parametrize("vector_field", ["position_m", "velocity_mps", "body_angular_velocity_rps", "target_position_m", "target_velocity_mps"])
def test_wrong_3d_vector_length_raises(vector_field):
    obs = _make_valid_obs()
    obs[vector_field] = [0.0, 1.0]
    with pytest.raises(MalformedObservationError, match=f"Observation {vector_field} must have length 3"):
        validate_observation_frame(obs)


@pytest.mark.parametrize("vector_field", ["position_m", "velocity_mps", "body_angular_velocity_rps", "target_position_m", "target_velocity_mps"])
def test_non_finite_in_3d_vector_raises(vector_field):
    obs = _make_valid_obs()
    obs[vector_field] = [0.0, float("nan"), 1.0]
    with pytest.raises(MalformedObservationError, match=f"Observation {vector_field}\\[1\\] must be a finite float"):
        validate_observation_frame(obs)


def test_quaternion_length_and_finiteness_raises():
    obs = _make_valid_obs()
    obs["orientation_quat_wxyz"] = [1.0, 0.0, 0.0]
    with pytest.raises(MalformedObservationError, match="orientation_quat_wxyz must have length 4"):
        validate_observation_frame(obs)

    obs["orientation_quat_wxyz"] = [1.0, 0.0, float("inf"), 0.0]
    with pytest.raises(MalformedObservationError, match="orientation_quat_wxyz\\[2\\] must be a finite float"):
        validate_observation_frame(obs)


def test_non_unit_quaternion_raises():
    obs = _make_valid_obs()
    obs["orientation_quat_wxyz"] = [2.0, 0.0, 0.0, 0.0]  # norm = 2.0 != 1.0
    with pytest.raises(MalformedObservationError, match="must be a unit quaternion"):
        validate_observation_frame(obs)


def test_sensor_fault_injection_still_passes_validation():
    """Sensor faults (noise, dropout, bias, latency) produce valid frames."""
    schedule = MissionFaultSchedule(
        sensor_faults=[
            SensorFaultSchedule(
                start_s=0.0,
                end_s=1.0,
                noise_pos_std_m=0.05,
                noise_vel_std_mps=0.1,
                bias_pos_m=[0.02, -0.01, 0.03],
                dropout_probability=0.2,
                latency_steps=2,
            )
        ]
    )
    injector = FaultInjector(schedule, seed=42)

    for step in range(20):
        t = step * 0.002
        true_obs = {
            "schema_version": "1.0",
            "trial_id": "sensor-fault-test",
            "step_index": step,
            "sim_time_s": t,
            "dt_s": 0.002,
            "position_m": [0.0, 0.0, 0.5 + 0.01 * step],
            "velocity_mps": [0.0, 0.0, 0.01],
            "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
            "body_angular_velocity_rps": [0.0, 0.0, 0.0],
            "target_position_m": [0.0, 0.0, 1.0],
            "target_velocity_mps": [0.0, 0.0, 0.0],
            "target_yaw_rad": 0.0,
            "active_stage_id": "stage_1",
            "stage_kind": "waypoint",
        }
        faulted_obs = injector.apply_sensor_faults(true_obs, t)
        validate_observation_frame(
            faulted_obs,
            expected_controller_dt_s=0.002,
            physics_dt_s=0.002,
            current_step_index=step,
        )


def test_api_run_mission_returns_500_on_malformed_observation(monkeypatch):
    """When the simulator constructs a corrupt observation frame, API returns 500 (not 502)."""
    import domnir.missions.simulator as sim_mod

    orig_val = sim_mod.validate_observation_frame

    def corrupt_validator(obs, **kwargs):
        raise MalformedObservationError("Simulated server physics corruption")

    monkeypatch.setattr(sim_mod, "validate_observation_frame", corrupt_validator)

    resp = client.post("/missions/run", json={"world_id": "open-field"})
    assert resp.status_code == 500
    assert "Malformed observation frame: Simulated server physics corruption" in resp.json()["detail"]

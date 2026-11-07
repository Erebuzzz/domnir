"""Unit tests for SafetyContract and Signal Temporal Logic (STL) monitoring."""

import math
import pytest
from domnir.contracts.stl import (
    PredicateType,
    SafetyContract,
    STLMonitor,
)
from domnir.spec import FlightSpec


def test_safety_contract_initialization_and_validation():
    contract = SafetyContract(
        target_altitude_m=0.10,
        altitude_tolerance_m=0.05,
        min_allowed_altitude_m=0.05,
        max_allowed_altitude_m=1.00,
        settling_time_s=0.15,
        mission_duration_s=0.40,
    )
    assert contract.physics_steps == 200
    assert contract.decimation == 5

    # Target below floor
    with pytest.raises(ValueError, match="strictly above minimum safety floor"):
        SafetyContract(target_altitude_m=0.04, min_allowed_altitude_m=0.05)

    # Settling time exceeding mission duration
    with pytest.raises(ValueError, match="cannot exceed or equal mission duration"):
        SafetyContract(settling_time_s=0.50, mission_duration_s=0.40)


def test_safety_contract_from_flight_spec():
    spec = FlightSpec(
        target_altitude_m=0.20,
        altitude_tolerance_m=0.08,
        min_allowed_altitude_m=0.06,
        max_allowed_altitude_m=1.50,
        mission_duration_s=0.60,
    )
    contract = SafetyContract.from_flight_spec(spec)
    assert contract.target_altitude_m == 0.20
    assert contract.altitude_tolerance_m == 0.08
    assert contract.physics_steps == 300


def test_stl_nominal_hover_trajectory_satisfied():
    contract = SafetyContract(
        target_altitude_m=0.10,
        altitude_tolerance_m=0.05,
        min_allowed_altitude_m=0.05,
        max_allowed_altitude_m=1.00,
        settling_time_s=0.10,
        mission_duration_s=0.20,
    )
    # Trajectory that stays at z=0.10, zero velocity, level attitude
    trajectory = [
        {
            "step_index": i,
            "sim_time_s": i * 0.002,
            "position_m": [0.0, 0.0, 0.10],
            "velocity_mps": [0.0, 0.0, 0.0],
            "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
        }
        for i in range(101)
    ]
    res = STLMonitor.evaluate_trajectory(contract, trajectory)
    assert res.satisfied is True
    assert res.verdict == "SATISFIED"
    assert res.min_robustness > 0.0
    # Expected floor margin: 0.10 - 0.05 = 0.05; tracking margin: 0.05 - 0.0 = 0.05
    assert math.isclose(res.min_robustness, 0.05, abs_tol=1e-5)


def test_stl_floor_breach_violation():
    contract = SafetyContract(
        target_altitude_m=0.10,
        min_allowed_altitude_m=0.05,
        max_allowed_altitude_m=1.00,
        settling_time_s=0.10,
    )
    # Trajectory drops to z=0.02 at step 50 (t=0.10s)
    trajectory = []
    for i in range(100):
        t = i * 0.002
        z = 0.08 if i != 50 else 0.02
        trajectory.append({
            "step_index": i,
            "sim_time_s": t,
            "position_m": [0.0, 0.0, z],
            "velocity_mps": [0.0, 0.0, 0.0],
            "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
        })

    res = STLMonitor.evaluate_trajectory(contract, trajectory)
    assert res.satisfied is False
    assert res.verdict == "VIOLATED"
    assert res.critical_predicate == PredicateType.FLOOR.value
    assert res.critical_step_index == 50
    assert math.isclose(res.critical_timestamp_s, 0.10, abs_tol=1e-4)
    # Robustness is 0.02 - 0.05 = -0.03
    assert math.isclose(res.min_robustness, -0.03, abs_tol=1e-5)


def test_stl_tracking_error_after_settling():
    contract = SafetyContract(
        target_altitude_m=0.10,
        altitude_tolerance_m=0.03,
        min_allowed_altitude_m=0.01,
        max_allowed_altitude_m=2.00,
        settling_time_s=0.10,
    )
    # Drift to z=0.15 at t=0.14s (step 70), outside tolerance 0.03 (error=0.05)
    trajectory = []
    for i in range(100):
        t = i * 0.002
        z = 0.10 if t < 0.12 else 0.15
        trajectory.append({
            "step_index": i,
            "sim_time_s": t,
            "position_m": [0.0, 0.0, z],
            "velocity_mps": [0.0, 0.0, 0.0],
            "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
        })

    res = STLMonitor.evaluate_trajectory(contract, trajectory)
    assert res.satisfied is False
    assert res.verdict == "VIOLATED"
    assert res.critical_predicate == PredicateType.TRACKING.value
    # Robustness: tolerance (0.03) - error (0.05) = -0.02
    assert math.isclose(res.min_robustness, -0.02, abs_tol=1e-5)


def test_stl_transient_tracking_grace_period():
    contract = SafetyContract(
        target_altitude_m=0.20,
        altitude_tolerance_m=0.02,
        min_allowed_altitude_m=0.01,
        max_allowed_altitude_m=2.00,
        settling_time_s=0.10,
        mission_duration_s=0.20,
    )
    # Starting from z=0.05 (error=0.15), climbs to 0.20 at t=0.08s and settles perfectly
    trajectory = []
    for i in range(100):
        t = i * 0.002
        z = 0.05 + min(0.15, t * 2.0)
        trajectory.append({
            "step_index": i,
            "sim_time_s": t,
            "position_m": [0.0, 0.0, z],
            "velocity_mps": [0.0, 0.0, 0.2],
            "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
        })

    res = STLMonitor.evaluate_trajectory(contract, trajectory)
    # Because error happens before settling_time (t < 0.10), tracking is not violated!
    assert res.satisfied is True
    assert res.verdict == "SATISFIED"
    assert res.is_valid is True


def test_stl_excessive_tilt_breach():
    contract = SafetyContract(
        max_tilt_deg=30.0,
        settling_time_s=0.05,
    )
    # 45 degree pitch tilt exceeds 30 deg ceiling
    q_45_pitch = [math.cos(math.pi / 8), 0.0, math.sin(math.pi / 8), 0.0]
    trajectory = [
        {
            "step_index": 0,
            "sim_time_s": 0.0,
            "position_m": [0.0, 0.0, 0.10],
            "velocity_mps": [0.0, 0.0, 0.0],
            "orientation_quat_wxyz": q_45_pitch,
        }
    ]
    res = STLMonitor.evaluate_trajectory(contract, trajectory)
    assert res.satisfied is False
    assert res.verdict == "VIOLATED"
    assert res.is_valid is True
    assert res.critical_predicate == PredicateType.TILT.value
    # Robustness is radians(30) - radians(45) < 0
    assert math.isclose(res.min_robustness, math.radians(30 - 45), abs_tol=1e-4)


def test_stl_negative_empty_and_nan_traces():
    contract = SafetyContract()
    # Empty
    empty_res = STLMonitor.evaluate_trajectory(contract, [])
    assert empty_res.verdict == "INVALID"
    assert empty_res.satisfied is False
    assert empty_res.is_valid is False
    assert empty_res.min_robustness == 0.0
    assert math.isfinite(empty_res.min_robustness)

    # NaN in position
    nan_traj = [
        {
            "step_index": 0,
            "sim_time_s": 0.0,
            "position_m": [0.0, 0.0, float("nan")],
            "velocity_mps": [0.0, 0.0, 0.0],
            "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
        }
    ]
    nan_res = STLMonitor.evaluate_trajectory(contract, nan_traj)
    assert nan_res.verdict == "INVALID"
    assert nan_res.is_valid is False
    assert nan_res.min_robustness == 0.0
    assert math.isfinite(nan_res.min_robustness)
    assert "Non-finite state" in nan_res.summary


def test_stl_truncated_trajectory_returns_invalid():
    contract = SafetyContract(
        target_altitude_m=0.10,
        mission_duration_s=0.40,
        physics_dt_s=0.002,
    )
    # Trajectory only has 20 steps (t=0.0 to 0.038s), far short of required 0.40s
    short_traj = [
        {
            "step_index": i,
            "sim_time_s": i * 0.002,
            "position_m": [0.0, 0.0, 0.10],
            "velocity_mps": [0.0, 0.0, 0.0],
            "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
        }
        for i in range(20)
    ]
    res = STLMonitor.evaluate_trajectory(contract, short_traj)
    assert res.verdict == "INVALID"
    assert res.satisfied is False
    assert res.is_valid is False
    assert res.min_robustness == 0.0
    assert "truncated" in res.summary.lower()


def test_stl_unnormalized_quaternion_returns_invalid():
    contract = SafetyContract(settling_time_s=0.01, mission_duration_s=0.02)
    # Quaternion with norm = 2.0 (breaches 0.05 tolerance)
    bad_quat_traj = [
        {
            "step_index": 0,
            "sim_time_s": 0.0,
            "position_m": [0.0, 0.0, 0.10],
            "velocity_mps": [0.0, 0.0, 0.0],
            "orientation_quat_wxyz": [2.0, 0.0, 0.0, 0.0],
        }
    ]
    res = STLMonitor.evaluate_trajectory(contract, bad_quat_traj)
    assert res.verdict == "INVALID"
    assert res.is_valid is False
    assert res.min_robustness == 0.0
    assert "quaternion" in res.summary.lower()


def test_stl_non_monotonic_timestamps_returns_invalid():
    contract = SafetyContract(settling_time_s=0.01, mission_duration_s=0.02)
    non_monotonic_traj = [
        {
            "step_index": 0,
            "sim_time_s": 0.002,
            "position_m": [0.0, 0.0, 0.10],
            "velocity_mps": [0.0, 0.0, 0.0],
            "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
        },
        {
            "step_index": 1,
            "sim_time_s": 0.001,  # Decreasing timestamp
            "position_m": [0.0, 0.0, 0.10],
            "velocity_mps": [0.0, 0.0, 0.0],
            "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
        },
    ]
    res = STLMonitor.evaluate_trajectory(contract, non_monotonic_traj)
    assert res.verdict == "INVALID"
    assert res.is_valid is False
    assert res.min_robustness == 0.0
    assert "non-monotonic" in res.summary.lower()


def test_stl_five_deliberately_invalid_evaluations_zero_violations():
    contract = SafetyContract(settling_time_s=0.05, mission_duration_s=0.10)
    invalids = [
        [],  # 1. Empty
        [{"step_index": 0, "sim_time_s": 0.0, "position_m": [0.0, 0.0, float("nan")], "velocity_mps": [0.0, 0.0, 0.0], "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0]}],  # 2. NaN
        [{"step_index": 0, "sim_time_s": 0.0, "position_m": [0.0, 0.0, 0.10], "velocity_mps": [0.0, 0.0, 0.0], "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0]}],  # 3. Truncated
        [{"step_index": 0, "sim_time_s": 0.0, "position_m": [0.0, 0.0, 0.10], "velocity_mps": [0.0, 0.0, 0.0], "orientation_quat_wxyz": [0.2, 0.0, 0.0, 0.0]}],  # 4. Unnormalized quat
        [{"step_index": 0, "sim_time_s": 0.05, "position_m": [0.0, 0.0, 0.10], "velocity_mps": [0.0, 0.0, 0.0], "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0]},
         {"step_index": 1, "sim_time_s": 0.02, "position_m": [0.0, 0.0, 0.10], "velocity_mps": [0.0, 0.0, 0.0], "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0]}],  # 5. Non-monotonic time
    ]

    violations_count = 0
    invalids_count = 0
    counterexamples = []

    for traj in invalids:
        res = STLMonitor.evaluate_trajectory(contract, traj)
        if res.is_valid and res.verdict == "VIOLATED":
            violations_count += 1
            counterexamples.append(res)
        if res.verdict == "INVALID":
            invalids_count += 1

    assert violations_count == 0
    assert invalids_count == 5
    assert len(counterexamples) == 0

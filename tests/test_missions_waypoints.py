"""Tests for Capability A: 3D Waypoint Navigation and Trajectory Tracking."""

import math
from pathlib import Path
import pytest

from domnir.controls.baseline_3d import Baseline3DController
from domnir.missions import (
    MissionConstraints,
    MissionProgressTracker,
    MissionSpecV2,
    MissionStage,
    MissionStageKind,
    ReferenceTrajectory,
    run_mission_simulation,
)
from domnir.spec import FlightSpec
from domnir.worlds import open_field_world


MODEL_PATH = Path("domnir/.cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")
if not MODEL_PATH.exists():
    MODEL_PATH = Path(".cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")


def test_mission_spec_v2_validation():
    stage1 = MissionStage(
        id="takeoff",
        kind=MissionStageKind.TAKEOFF,
        target_position_m=[0.0, 0.0, 0.20],
        tolerance_m=0.08,
        dwell_s=0.05,
        completion_deadline_s=0.50,
    )
    stage2 = MissionStage(
        id="wp1",
        kind=MissionStageKind.WAYPOINT,
        target_position_m=[0.30, 0.20, 0.35],
        tolerance_m=0.10,
        dwell_s=0.05,
        completion_deadline_s=1.20,
    )
    spec = MissionSpecV2(
        mission_id="test-waypoints",
        stages=[stage1, stage2],
        constraints=MissionConstraints(max_speed_mps=3.0, max_tilt_deg=45.0),
    )
    assert len(spec.stages) == 2
    assert spec.total_mission_duration_s == 1.20
    assert spec.physics_steps == int(1.20 / 0.002)


def test_mission_spec_v2_from_legacy_flight_spec():
    legacy = FlightSpec(target_altitude_m=0.15, mission_duration_s=0.40)
    spec_v2 = MissionSpecV2.from_flight_spec(legacy)
    assert spec_v2.stages[0].kind == MissionStageKind.TAKEOFF
    assert spec_v2.stages[1].kind == MissionStageKind.WAYPOINT
    assert spec_v2.stages[1].target_position_m[2] == pytest.approx(0.15)
    assert spec_v2.total_mission_duration_s == pytest.approx(0.40)


def test_reference_trajectory_interpolation_and_feasibility():
    stages = [
        MissionStage(
            id="takeoff",
            kind=MissionStageKind.TAKEOFF,
            target_position_m=[0.0, 0.0, 0.20],
            completion_deadline_s=0.50,
        ),
        MissionStage(
            id="wp1",
            kind=MissionStageKind.WAYPOINT,
            target_position_m=[0.40, 0.30, 0.30],
            completion_deadline_s=1.50,
        ),
    ]
    spec = MissionSpecV2(mission_id="feasibility-test", stages=stages)
    traj = ReferenceTrajectory(spec, initial_position_m=[0.0, 0.0, 0.0])

    s0 = traj.sample(0.0)
    assert s0["position_m"] == [0.0, 0.0, 0.0]

    s_mid = traj.sample(0.25)
    assert 0.0 < s_mid["position_m"][2] < 0.20

    s_end = traj.sample(1.50)
    assert s_end["position_m"][0] == pytest.approx(0.40)
    assert s_end["position_m"][1] == pytest.approx(0.30)
    assert s_end["position_m"][2] == pytest.approx(0.30)

    feasible, msg = traj.check_feasibility()
    assert feasible is True


def test_mission_progress_tracker_dwell_and_advance():
    stages = [
        MissionStage(
            id="wp1",
            kind=MissionStageKind.WAYPOINT,
            target_position_m=[0.10, 0.0, 0.20],
            tolerance_m=0.05,
            dwell_s=0.010,
            completion_deadline_s=0.50,
        ),
        MissionStage(
            id="wp2",
            kind=MissionStageKind.WAYPOINT,
            target_position_m=[0.30, 0.0, 0.20],
            tolerance_m=0.05,
            dwell_s=0.010,
            completion_deadline_s=1.00,
        ),
    ]
    spec = MissionSpecV2(mission_id="dwell-test", stages=stages)
    tracker = MissionProgressTracker(spec)

    # 1. Close to target wp1
    res1 = tracker.update(0.05, 25, [0.10, 0.0, 0.20], [0.0, 0.0, 0.0], dt_s=0.005)
    assert res1["active_stage_id"] == "wp1"
    assert res1["stage_advanced"] is False

    # 2. Complete dwell for wp1 -> should advance to wp2
    res2 = tracker.update(0.06, 30, [0.10, 0.0, 0.20], [0.0, 0.0, 0.0], dt_s=0.005)
    assert res2["stage_advanced"] is True
    assert res2["active_stage_id"] == "wp2"


def test_baseline_3d_controller_executes_waypoint_mission():
    if not MODEL_PATH.exists():
        pytest.skip(f"MuJoCo cf2.xml model not found at {MODEL_PATH}")

    stages = [
        MissionStage(
            id="takeoff",
            kind=MissionStageKind.TAKEOFF,
            target_position_m=[0.0, 0.0, 0.15],
            tolerance_m=0.06,
            dwell_s=0.02,
            completion_deadline_s=0.25,
        ),
        MissionStage(
            id="waypoint_east",
            kind=MissionStageKind.WAYPOINT,
            target_position_m=[0.10, 0.05, 0.18],
            tolerance_m=0.08,
            dwell_s=0.02,
            completion_deadline_s=0.60,
        ),
    ]
    spec = MissionSpecV2(
        mission_id="waypoint-e2e",
        stages=stages,
        constraints=MissionConstraints(
            min_altitude_m=0.02,
            max_altitude_m=0.80,
            max_tilt_deg=50.0,
        ),
    )
    world = open_field_world()
    ctrl = Baseline3DController()

    res = run_mission_simulation(
        MODEL_PATH,
        spec,
        world,
        lambda obs: ctrl.compute_action(obs),
        initial_pos_m=[0.0, 0.0, 0.05],
    )

    assert res.evaluation.physical_verdict == "NOT_FALSIFIED"
    assert res.replay_matched is True
    assert len(res.trajectory) == spec.physics_steps
    assert len(res.actions) == spec.physics_steps

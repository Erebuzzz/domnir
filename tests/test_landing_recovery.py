"""Tests for Capability D: Precision Landing, Abort, and Emergency Recovery."""

from pathlib import Path
import pytest

from domnir.controls.baseline_3d import Baseline3DController
from domnir.missions import (
    MissionConstraints,
    MissionSpecV2,
    MissionStage,
    MissionStageKind,
    run_mission_simulation,
)
from domnir.worlds import EntityKind, Pose3D, WorldEntity, WorldSpec, precision_landing_world


MODEL_PATH = Path("domnir/.cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")
if not MODEL_PATH.exists():
    MODEL_PATH = Path(".cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")


def test_precision_landing_safe_touchdown():
    if not MODEL_PATH.exists():
        pytest.skip(f"MuJoCo cf2.xml model not found at {MODEL_PATH}")

    pad = WorldEntity(
        id="pad",
        kind=EntityKind.LANDING_PAD,
        pose=Pose3D(position_m=[0.10, 0.0, 0.02]),
        dimensions_m=[0.25, 0.25, 0.04],
        contact_class="allowed-touchdown",
    )
    world = WorldSpec(world_id="landing-test-world", entities=[pad])

    stages = [
        MissionStage(
            id="approach",
            kind=MissionStageKind.WAYPOINT,
            target_position_m=[0.10, 0.0, 0.08],
            tolerance_m=0.06,
            dwell_s=0.02,
            completion_deadline_s=0.20,
        ),
        MissionStage(
            id="touchdown",
            kind=MissionStageKind.LANDING,
            target_position_m=[0.10, 0.0, 0.02],
            tolerance_m=0.08,
            dwell_s=0.02,
            completion_deadline_s=1.00,
        ),
    ]
    spec = MissionSpecV2(
        mission_id="safe-landing",
        stages=stages,
        constraints=MissionConstraints(
            min_altitude_m=0.01,
            max_landing_impact_speed_mps=1.0,
            fail_on_unpermitted_contact=True,
        ),
    )
    ctrl = Baseline3DController()

    res = run_mission_simulation(
        MODEL_PATH,
        spec,
        world,
        lambda obs: ctrl.compute_action(obs),
        initial_pos_m=[0.10, 0.0, 0.10],
    )

    assert res.replay_matched is True
    # Physical flight constraints satisfied
    assert res.evaluation.physical_verdict == "NOT_FALSIFIED"
    # Pad contact recorded
    touchdowns = [c for c in res.contacts if c.contact_class == "allowed-touchdown"]
    assert len(touchdowns) > 0


def test_high_impact_hard_landing_falsifies_safety():
    if not MODEL_PATH.exists():
        pytest.skip(f"MuJoCo cf2.xml model not found at {MODEL_PATH}")

    pad = WorldEntity(
        id="pad",
        kind=EntityKind.LANDING_PAD,
        pose=Pose3D(position_m=[0.0, 0.0, 0.02]),
        dimensions_m=[0.30, 0.30, 0.04],
        contact_class="allowed-touchdown",
    )
    world = WorldSpec(world_id="hard-landing-world", entities=[pad])

    stages = [
        MissionStage(
            id="slam",
            kind=MissionStageKind.LANDING,
            target_position_m=[0.0, 0.0, 0.03],
            tolerance_m=0.06,
            dwell_s=0.02,
            completion_deadline_s=0.30,
        )
    ]
    # Strict maximum landing speed constraint
    spec = MissionSpecV2(
        mission_id="hard-slam-test",
        stages=stages,
        constraints=MissionConstraints(
            min_altitude_m=0.01,
            max_landing_impact_speed_mps=0.10,  # Strict: 0.10 m/s
        ),
    )

    # Free fall controller shutting off thrust to cause hard slam
    def freefall_controller(obs):
        return {
            "schema_version": "1.0",
            "trial_id": obs.get("trial_id", "t"),
            "step_index": obs.get("step_index", 0),
            "thrust": 0.0,
            "moment_x": 0.0,
            "moment_y": 0.0,
            "moment_z": 0.0,
        }

    res = run_mission_simulation(
        MODEL_PATH,
        spec,
        world,
        freefall_controller,
        initial_pos_m=[0.0, 0.0, 0.20],
    )

    assert res.evaluation.physical_verdict == "FALSIFIED"
    assert "Landing impact speed" in res.evaluation.summary
    assert res.replay_matched is True


def test_abort_and_emergency_recovery_stage():
    if not MODEL_PATH.exists():
        pytest.skip(f"MuJoCo cf2.xml model not found at {MODEL_PATH}")

    stages = [
        MissionStage(
            id="normal_waypoint",
            kind=MissionStageKind.WAYPOINT,
            target_position_m=[0.05, 0.0, 0.15],
            tolerance_m=0.06,
            dwell_s=0.02,
            completion_deadline_s=0.25,
        ),
        MissionStage(
            id="emergency_climb",
            kind=MissionStageKind.RECOVERY,
            target_position_m=[0.05, 0.0, 0.25],
            tolerance_m=0.06,
            dwell_s=0.02,
            completion_deadline_s=0.60,
        ),
    ]
    spec = MissionSpecV2(
        mission_id="recovery-test",
        stages=stages,
        constraints=MissionConstraints(min_altitude_m=0.02, max_altitude_m=0.60),
    )
    world = precision_landing_world()
    ctrl = Baseline3DController()

    res = run_mission_simulation(
        MODEL_PATH,
        spec,
        world,
        lambda obs: ctrl.compute_action(obs),
        initial_pos_m=[0.05, 0.0, 0.10],
    )

    assert res.evaluation.physical_verdict == "NOT_FALSIFIED"
    assert res.replay_matched is True
    # Recovery stage successfully entered and recorded
    stage_ids = [s["stage_id"] for s in res.evaluation.stage_results]
    assert "emergency_climb" in stage_ids

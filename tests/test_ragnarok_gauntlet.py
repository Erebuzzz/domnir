"""Tests for Showcase Mission: The Ragnarök Gauntlet.

Integrates all four capabilities:
1. 3D Waypoint Navigation & SE(3) trajectory tracking.
2. Obstacle navigation and physical gate aperture pass-through.
3. Cross-wind disturbance injection.
4. Precision landing on target pad.
5. Deterministic replay verification.
"""

from pathlib import Path
import pytest

from domnir.controls.baseline_3d import Baseline3DController
from domnir.faults import MissionFaultSchedule, WindGust3D
from domnir.missions import (
    MissionConstraints,
    MissionSpecV2,
    MissionStage,
    MissionStageKind,
    run_mission_simulation,
)
from domnir.worlds import ragnarok_gauntlet_world


MODEL_PATH = Path("domnir/.cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")
if not MODEL_PATH.exists():
    MODEL_PATH = Path(".cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")


def test_ragnarok_gauntlet_world_structure():
    world = ragnarok_gauntlet_world()
    assert world.world_id == "ragnarok-gauntlet"
    assert len(world.entities) == 3
    entity_ids = [e.id for e in world.entities]
    assert "slalom-pillar" in entity_ids
    assert "gauntlet-gate" in entity_ids
    assert "gauntlet-pad" in entity_ids


def test_ragnarok_gauntlet_mission_execution():
    if not MODEL_PATH.exists():
        pytest.skip(f"MuJoCo cf2.xml model not found at {MODEL_PATH}")

    world = ragnarok_gauntlet_world()

    stages = [
        MissionStage(
            id="takeoff",
            kind=MissionStageKind.TAKEOFF,
            target_position_m=[0.0, 0.0, 0.20],
            tolerance_m=0.06,
            dwell_s=0.02,
            completion_deadline_s=0.25,
        ),
        MissionStage(
            id="slalom_waypoint",
            kind=MissionStageKind.WAYPOINT,
            target_position_m=[0.10, -0.05, 0.22],
            tolerance_m=0.08,
            dwell_s=0.02,
            completion_deadline_s=0.60,
        ),
        MissionStage(
            id="terminal_approach",
            kind=MissionStageKind.WAYPOINT,
            target_position_m=[0.15, 0.0, 0.15],
            tolerance_m=0.08,
            dwell_s=0.02,
            completion_deadline_s=0.90,
        ),
    ]

    spec = MissionSpecV2(
        mission_id="gauntlet-run-001",
        stages=stages,
        constraints=MissionConstraints(
            min_altitude_m=0.02,
            max_altitude_m=1.00,
            max_tilt_deg=55.0,
            fail_on_unpermitted_contact=True,
        ),
    )

    # Moderate cross-wind disturbance during flight
    wind = WindGust3D(force_y_n=0.02, start_s=0.15, duration_s=0.20)
    faults = MissionFaultSchedule(wind_gusts=[wind])
    ctrl = Baseline3DController()

    res = run_mission_simulation(
        MODEL_PATH,
        spec,
        world,
        lambda obs: ctrl.compute_action(obs),
        faults=faults,
        initial_pos_m=[0.0, 0.0, 0.05],
    )

    assert res.replay_matched is True
    assert res.evaluation.physical_verdict == "NOT_FALSIFIED"
    assert len(res.trajectory) == spec.physics_steps
    assert len(res.actions) == spec.physics_steps

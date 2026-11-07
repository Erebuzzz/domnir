"""Tests for Capability B: Physical Obstacle Avoidance, Gates, and Navigation Corridors."""

from pathlib import Path
import mujoco
import pytest

from domnir.controls.baseline_3d import Baseline3DController
from domnir.missions import (
    MissionConstraints,
    MissionSpecV2,
    MissionStage,
    MissionStageKind,
    run_mission_simulation,
)
from domnir.safety.mission_monitor import MissionSafetyMonitor
from domnir.worlds import (
    EntityKind,
    MJCFWorldCompiler,
    Pose3D,
    WorldEntity,
    WorldSpec,
    gate_corridor_world,
    open_field_world,
)

MODEL_PATH = Path("domnir/.cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")
if not MODEL_PATH.exists():
    MODEL_PATH = Path(".cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")


def test_world_spec_entity_lookup():
    world = gate_corridor_world()
    gate = world.get_entity("gate-1")
    assert gate is not None
    assert gate.kind == EntityKind.GATE
    assert gate.aperture_m == [0.45, 0.45]
    assert gate.contact_class == "obstacle"


def test_gate_aperture_is_physically_passable():
    """Verify that gate center aperture is physically open while frame bars cause contact."""
    world = gate_corridor_world()
    xml_str = MJCFWorldCompiler.compile(MODEL_PATH, world)
    model = mujoco.MjModel.from_xml_string(xml_str)
    data = mujoco.MjData(model)

    # 1. Place Crazyflie directly in the center of the gate aperture: [0.65, 0.0, 0.35]
    data.qpos[0] = 0.65
    data.qpos[1] = 0.00
    data.qpos[2] = 0.35
    data.qpos[3] = 1.0
    mujoco.mj_forward(model, data)

    # Should have zero contact with any gate geom
    gate_contacts = []
    for i in range(data.ncon):
        c = data.contact[i]
        g1 = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, c.geom1) or ""
        g2 = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, c.geom2) or ""
        if "gate" in g1 or "gate" in g2:
            gate_contacts.append((g1, g2))

    assert len(gate_contacts) == 0, f"Expected open gate aperture, but contacts detected: {gate_contacts}"

    # 2. Place Crazyflie on the right post frame: [0.65, 0.25, 0.35]
    data.qpos[0] = 0.65
    data.qpos[1] = 0.25
    data.qpos[2] = 0.35
    mujoco.mj_forward(model, data)

    frame_contacts = []
    for i in range(data.ncon):
        c = data.contact[i]
        g1 = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, c.geom1) or ""
        g2 = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, c.geom2) or ""
        if "gate" in g1 or "gate" in g2:
            frame_contacts.append((g1, g2))

    assert len(frame_contacts) > 0, "Expected collision with gate frame post, but none detected"


def test_obstacle_collision_falsifies_safety():
    """A mission trajectory colliding with an obstacle is evaluated as FALSIFIED."""
    # Obstacle placed directly in flight path at x=0.10, y=0.0, z=0.15
    obs = WorldEntity(
        id="blocker",
        kind=EntityKind.BOX_OBSTACLE,
        pose=Pose3D(position_m=[0.10, 0.0, 0.15]),
        dimensions_m=[0.08, 0.20, 0.20],
        contact_class="obstacle",
    )
    world = WorldSpec(world_id="obstacle-test", entities=[obs])

    stages = [
        MissionStage(
            id="crash_target",
            kind=MissionStageKind.WAYPOINT,
            target_position_m=[0.35, 0.0, 0.15],
            completion_deadline_s=0.50,
        )
    ]
    spec = MissionSpecV2(
        mission_id="collision-test",
        stages=stages,
        constraints=MissionConstraints(fail_on_unpermitted_contact=True),
    )
    ctrl = Baseline3DController()

    res = run_mission_simulation(
        MODEL_PATH,
        spec,
        world,
        lambda obs: ctrl.compute_action(obs),
        initial_pos_m=[0.05, 0.0, 0.15],
    )

    # Must detect obstacle collision contact
    obs_contacts = [c for c in res.contacts if c.contact_class == "obstacle"]
    assert len(obs_contacts) > 0
    assert res.evaluation.physical_verdict == "FALSIFIED"
    assert "Forbidden obstacle contact" in res.evaluation.summary

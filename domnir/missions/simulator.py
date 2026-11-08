"""Trusted 3D multi-mission simulation and replay kernel."""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path
from typing import Any, Callable
import mujoco
import numpy as np

from domnir.controls.baseline_3d import Baseline3DController
from domnir.faults.injector import FaultInjector
from domnir.faults.schema import MissionFaultSchedule
from domnir.missions.planner import ReferenceTrajectory
from domnir.missions.progress import MissionProgressTracker
from domnir.missions.schema import MissionSpecV2, MissionStageKind
from domnir.protocol import ActionBounds, parse_action
from domnir.safety.mission_monitor import ContactEvent, MissionSafetyEvaluation, MissionSafetyMonitor
from domnir.worlds.compiler import MJCFWorldCompiler
from domnir.worlds.schema import WorldSpec


class MissionCancelledError(RuntimeError):
    """Raised when a caller cancels a mission run before it finishes."""


class MissionWallTimeExceededError(RuntimeError):
    """Raised when a mission run exceeds its wall-clock budget."""


class MissionSimulationResult:
    def __init__(
        self,
        *,
        mission: MissionSpecV2,
        world: WorldSpec,
        trajectory: list[dict[str, Any]],
        actions: list[list[float]],
        contacts: list[ContactEvent],
        evaluation: MissionSafetyEvaluation,
        replay_max_abs_diff: float,
        replay_matched: bool,
    ) -> None:
        self.mission = mission
        self.world = world
        self.trajectory = trajectory
        self.actions = actions
        self.contacts = contacts
        self.evaluation = evaluation
        self.replay_max_abs_diff = replay_max_abs_diff
        self.replay_matched = replay_matched


def run_mission_simulation(
    base_model_path: Path,
    mission: MissionSpecV2,
    world: WorldSpec,
    controller_fn: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    fault_schedule: MissionFaultSchedule | None = None,
    faults: MissionFaultSchedule | None = None,
    seed: int = 42,
    initial_pos_m: list[float] | None = None,
    max_wall_time_s: float | None = None,
    cancel_event: threading.Event | None = None,
) -> MissionSimulationResult:
    """Execute complete 3D mission in trusted MuJoCo physics engine.

    ``max_wall_time_s`` and ``cancel_event`` are checked before every control
    step; when either trips, the run stops with ``MissionWallTimeExceededError``
    or ``MissionCancelledError`` and no partial verdict is produced. The caller
    owns any guest resources and must tear them down.
    """
    started = time.monotonic()
    effective_faults = fault_schedule if fault_schedule is not None else faults
    # 1. Compile world geometry into MuJoCo MJCF XML
    compiled_xml = MJCFWorldCompiler.compile(base_model_path, world)
    model = mujoco.MjModel.from_xml_string(compiled_xml)
    data = mujoco.MjData(model)

    cf2_body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
    if cf2_body_id < 0:
        raise ValueError("Crazyflie body 'cf2' not found in model")

    # Initial position
    p0 = initial_pos_m or [0.0, 0.0, 0.05]
    data.qpos[0] = float(p0[0])
    data.qpos[1] = float(p0[1])
    data.qpos[2] = float(p0[2])
    data.qpos[3] = 1.0  # w
    data.qpos[4] = 0.0  # x
    data.qpos[5] = 0.0  # y
    data.qpos[6] = 0.0  # z
    mujoco.mj_forward(model, data)

    bounds = ActionBounds(
        tuple(float(x) for x in model.actuator_ctrlrange[:, 0]),
        tuple(float(x) for x in model.actuator_ctrlrange[:, 1]),
    )

    progress = MissionProgressTracker(mission)
    planner = ReferenceTrajectory(mission, initial_position_m=p0)
    injector = FaultInjector(effective_faults, seed=seed)

    steps = mission.physics_steps
    dt = mission.physics_dt_s

    trajectory: list[dict[str, Any]] = []
    recorded_actions: list[list[float]] = []
    recorded_states: list[np.ndarray] = [np.concatenate((data.qpos, data.qvel))]
    contacts: list[ContactEvent] = []

    for step_idx in range(steps):
        if cancel_event is not None and cancel_event.is_set():
            raise MissionCancelledError(f"Mission cancelled at step {step_idx} of {steps}")
        if max_wall_time_s is not None and time.monotonic() - started > max_wall_time_s:
            raise MissionWallTimeExceededError(
                f"Mission exceeded wall-time budget of {max_wall_time_s:.1f}s at step {step_idx} of {steps}"
            )
        sim_time = float(data.time)
        pos = data.qpos[:3].tolist()
        vel = data.qvel[:3].tolist()
        quat = data.qpos[3:7].tolist()
        omega = data.qvel[3:6].tolist()

        # Check contact with pad
        pad_contact = any(
            c.contact_class == "allowed-touchdown" and c.step_index == step_idx - 1
            for c in contacts
        )

        # Update stage progress
        prog_info = progress.update(
            sim_time,
            step_idx,
            pos,
            vel,
            pad_contact=pad_contact,
            dt_s=dt,
        )

        ref_sample = planner.sample(sim_time)

        # Build true observation
        true_observation = {
            "schema_version": "1.0",
            "trial_id": f"mission-{mission.mission_id}",
            "step_index": step_idx,
            "sim_time_s": sim_time,
            "dt_s": dt,
            "position_m": pos,
            "velocity_mps": vel,
            "orientation_quat_wxyz": quat,
            "body_angular_velocity_rps": omega,
            "target_position_m": prog_info["target_position_m"],
            "target_velocity_mps": ref_sample["velocity_mps"],
            "target_yaw_rad": ref_sample["yaw_rad"],
            "active_stage_id": prog_info["active_stage_id"],
            "stage_kind": prog_info["stage_kind"],
        }

        # Fault injection on guest observation
        guest_obs = injector.apply_sensor_faults(true_observation, sim_time)

        # Call controller
        raw_action_dict = controller_fn(guest_obs)

        # Validate action
        raw_bytes = str(raw_action_dict).replace("'", '"').encode("utf-8")
        parsed = parse_action(
            raw_bytes,
            trial_id=f"mission-{mission.mission_id}",
            step_index=step_idx,
            bounds=bounds,
        )

        # Apply actuator derating if active
        effective_action = injector.apply_actuator_derating(parsed, sim_time)
        recorded_actions.append(list(parsed))

        # Apply action to MuJoCo
        data.ctrl[:] = effective_action

        # Apply 3D wind disturbance to Crazyflie body
        wind_f = injector.get_applied_wind_force_n(sim_time)
        data.xfrc_applied[cf2_body_id, :3] = wind_f

        # Step physics
        mujoco.mj_step(model, data)
        recorded_states.append(np.concatenate((data.qpos, data.qvel)))

        # Detect contacts
        for c_idx in range(data.ncon):
            con = data.contact[c_idx]
            g1_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, con.geom1) or f"geom_{con.geom1}"
            g2_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, con.geom2) or f"geom_{con.geom2}"

            # Determine if contact involves Crazyflie
            is_cf2 = (
                model.geom_bodyid[con.geom1] == cf2_body_id
                or model.geom_bodyid[con.geom2] == cf2_body_id
                or "cf2" in g1_name
                or "cf2" in g2_name
            )
            if not is_cf2:
                continue

            pair_name = f"{g1_name} {g2_name}".lower()
            if "landingpad" in pair_name:
                c_class = "allowed-touchdown"
            elif "obstacle" in pair_name or "gate" in pair_name or "wall" in pair_name:
                c_class = "obstacle"
            elif "floor" in pair_name:
                c_class = "floor"
            else:
                c_class = "floor"

            impact_v = math.sqrt(vel[0] ** 2 + vel[1] ** 2 + vel[2] ** 2)
            contacts.append(
                ContactEvent(
                    step_index=step_idx,
                    sim_time_s=sim_time,
                    geom1=g1_name,
                    geom2=g2_name,
                    contact_class=c_class,
                    impact_velocity_mps=round(impact_v, 4),
                    position_m=pos,
                )
            )

        trajectory.append({
            "step_index": step_idx,
            "sim_time_s": sim_time,
            "position_m": pos,
            "velocity_mps": vel,
            "orientation_quat_wxyz": quat,
            "active_stage_id": prog_info["active_stage_id"],
            "distance_to_target_m": prog_info["distance_to_target_m"],
            "action": list(parsed),
            "effective_action": list(effective_action),
            "wind_force_n": wind_f,
        })

    # Any stage still active when the flight ends did not finish in time.
    progress.finalize(float(data.time))

    # Evaluate safety and mission completion
    evaluation = MissionSafetyMonitor.evaluate(
        mission,
        world,
        trajectory,
        contacts,
        progress.stage_history,
    )

    # Independent physical replay verification
    replay_model = mujoco.MjModel.from_xml_string(compiled_xml)
    replay_data = mujoco.MjData(replay_model)
    replay_data.qpos[0] = float(p0[0])
    replay_data.qpos[1] = float(p0[1])
    replay_data.qpos[2] = float(p0[2])
    replay_data.qpos[3] = 1.0
    mujoco.mj_forward(replay_model, replay_data)

    max_diff = 0.0
    for s_idx, act in enumerate(recorded_actions):
        t_now = float(replay_data.time)
        # Re-apply wind force
        w_f = injector.get_applied_wind_force_n(t_now)
        replay_data.xfrc_applied[cf2_body_id, :3] = w_f
        # Re-apply effective derated action
        eff_act = injector.apply_actuator_derating(tuple(act), t_now)
        replay_data.ctrl[:] = eff_act
        mujoco.mj_step(replay_model, replay_data)

        orig_st = recorded_states[s_idx + 1]
        rep_st = np.concatenate((replay_data.qpos, replay_data.qvel))
        diff = float(np.max(np.abs(orig_st - rep_st)))
        if diff > max_diff:
            max_diff = diff

    replay_matched = max_diff <= 1e-12

    return MissionSimulationResult(
        mission=mission,
        world=world,
        trajectory=trajectory,
        actions=recorded_actions,
        contacts=contacts,
        evaluation=evaluation,
        replay_max_abs_diff=max_diff,
        replay_matched=replay_matched,
    )

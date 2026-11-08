"""Trusted 3D multi-mission simulation and replay kernel.

One flight loop (``fly``) is used for the live run, the in-process replay
check and independent Court Record verification. It either asks a controller
for actions or replays recorded ones; everything else (physics, wind,
actuator derating, contact classification, stage tracking) is identical.

Controller rate: the controller is invoked once every
``mission.controller_period_steps`` physics steps and its action is held
(zero-order hold) in between. ``recorded_controller_actions`` therefore has
one entry per invocation, not per physics step.
"""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import mujoco
import numpy as np

from domnir.faults.injector import FaultInjector
from domnir.faults.schema import MissionFaultSchedule
from domnir.missions.planner import ReferenceTrajectory
from domnir.missions.progress import MissionProgressTracker
from domnir.missions.schema import MissionSpecV2
from domnir.protocol import ActionBounds, InvalidFrame, parse_action
from domnir.replay import capture_integration_state
from domnir.safety.mission_monitor import ContactEvent, MissionSafetyEvaluation, MissionSafetyMonitor
from domnir.worlds.compiler import MJCFWorldCompiler
from domnir.worlds.schema import WorldSpec

REPLAY_TOLERANCE = 1e-12
CHECKPOINT_INTERVAL_STEPS = 25
REFERENCE_PATH_SAMPLES = 120


class MissionCancelledError(RuntimeError):
    """Raised when a caller cancels a mission run before it finishes."""


class MissionWallTimeExceededError(RuntimeError):
    """Raised when a mission run exceeds its wall-clock budget."""


class MalformedObservationError(RuntimeError):
    """Raised when an observation frame violates schema, dimensions, or physical consistency."""


def validate_observation_frame(
    obs: Any,
    *,
    expected_controller_dt_s: float | None = None,
    physics_dt_s: float | None = None,
    current_step_index: int | None = None,
) -> None:
    """Validate an observation frame delivered to a flight controller.

    Ensures required fields, finite values, proper vector dimensions, unit quaternion,
    matching controller dt, and step/time consistency with physics.
    """
    if not isinstance(obs, dict):
        raise MalformedObservationError(f"Observation frame must be a dict, got {type(obs).__name__}")

    required_keys = (
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
    )
    for k in required_keys:
        if k not in obs:
            raise MalformedObservationError(f"Missing required observation field: {k}")

    if obs["schema_version"] != "1.0":
        raise MalformedObservationError(f"Invalid observation schema_version: {obs['schema_version']!r}")

    if not isinstance(obs["trial_id"], str) or not obs["trial_id"].strip():
        raise MalformedObservationError("Observation trial_id must be a non-empty string")

    step_idx = obs["step_index"]
    if not isinstance(step_idx, int) or isinstance(step_idx, bool) or step_idx < 0:
        raise MalformedObservationError(f"Observation step_index must be a non-negative integer, got {step_idx!r}")

    if current_step_index is not None and step_idx > current_step_index:
        raise MalformedObservationError(
            f"Observation step_index {step_idx} exceeds current step {current_step_index}"
        )

    sim_time = obs["sim_time_s"]
    if not isinstance(sim_time, (int, float)) or not math.isfinite(sim_time) or sim_time < 0.0:
        raise MalformedObservationError(
            f"Observation sim_time_s must be a finite non-negative float, got {sim_time!r}"
        )

    if physics_dt_s is not None and physics_dt_s > 0:
        expected_time = step_idx * physics_dt_s
        if abs(sim_time - expected_time) > 1e-6:
            raise MalformedObservationError(
                f"Observation sim_time_s {sim_time:.6f} inconsistent with step_index {step_idx} * physics_dt ({expected_time:.6f})"
            )

    dt_s = obs["dt_s"]
    if not isinstance(dt_s, (int, float)) or not math.isfinite(dt_s) or dt_s <= 0.0:
        raise MalformedObservationError(f"Observation dt_s must be a positive finite float, got {dt_s!r}")

    if expected_controller_dt_s is not None:
        if abs(dt_s - expected_controller_dt_s) > 1e-9:
            raise MalformedObservationError(
                f"Observation dt_s {dt_s} does not match expected controller_dt_s {expected_controller_dt_s}"
            )

    target_yaw = obs["target_yaw_rad"]
    if not isinstance(target_yaw, (int, float)) or not math.isfinite(target_yaw):
        raise MalformedObservationError(f"Observation target_yaw_rad must be a finite float, got {target_yaw!r}")

    if not isinstance(obs["active_stage_id"], str) or not obs["active_stage_id"]:
        raise MalformedObservationError("Observation active_stage_id must be a non-empty string")

    if not isinstance(obs["stage_kind"], str) or not obs["stage_kind"]:
        raise MalformedObservationError("Observation stage_kind must be a non-empty string")

    vectors_3d = (
        ("position_m", obs["position_m"]),
        ("velocity_mps", obs["velocity_mps"]),
        ("body_angular_velocity_rps", obs["body_angular_velocity_rps"]),
        ("target_position_m", obs["target_position_m"]),
        ("target_velocity_mps", obs["target_velocity_mps"]),
    )
    for name, vec in vectors_3d:
        if not isinstance(vec, (list, tuple)):
            raise MalformedObservationError(f"Observation {name} must be a list or tuple of 3 floats, got {type(vec).__name__}")
        if len(vec) != 3:
            raise MalformedObservationError(f"Observation {name} must have length 3, got length {len(vec)}")
        for i, v in enumerate(vec):
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise MalformedObservationError(f"Observation {name}[{i}] must be a finite float, got {v!r}")

    quat = obs["orientation_quat_wxyz"]
    if not isinstance(quat, (list, tuple)):
        raise MalformedObservationError(f"Observation orientation_quat_wxyz must be a list or tuple of 4 floats, got {type(quat).__name__}")
    if len(quat) != 4:
        raise MalformedObservationError(f"Observation orientation_quat_wxyz must have length 4, got length {len(quat)}")
    for i, q in enumerate(quat):
        if not isinstance(q, (int, float)) or not math.isfinite(q):
            raise MalformedObservationError(f"Observation orientation_quat_wxyz[{i}] must be a finite float, got {q!r}")
    q_norm = math.sqrt(sum(float(q) ** 2 for q in quat))
    if abs(q_norm - 1.0) > 1e-2:
        raise MalformedObservationError(
            f"Observation orientation_quat_wxyz must be a unit quaternion (|q| = 1.0), got norm {q_norm:.6f}"
        )


def encode_action_payload(raw: Any) -> bytes:
    """Turn a controller's return value into the bytes ``parse_action`` checks.

    Guests return JSON text, which is validated as-is (so duplicate keys or
    NaN are rejected by the protocol parser). In-process controllers return a
    dict, which is encoded with a real JSON encoder.
    """
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    if isinstance(raw, str):
        return raw.encode("utf-8")
    try:
        return json.dumps(raw, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InvalidFrame(f"Action is not a JSON-serializable frame: {exc}") from exc


def compile_world_xml(base_model_path: Path, world: WorldSpec) -> str:
    return MJCFWorldCompiler.compile(base_model_path, world)


def classify_contact(pair_name: str) -> str:
    if "landingpad" in pair_name:
        return "allowed-touchdown"
    if "obstacle" in pair_name or "gate" in pair_name or "wall" in pair_name:
        return "obstacle"
    return "floor"


@dataclass
class FlightRun:
    trajectory: list[dict[str, Any]]
    step_actions: list[list[float]]
    controller_actions: list[list[float]]
    contacts: list[ContactEvent]
    stage_history: list[dict[str, Any]]
    evaluation: MissionSafetyEvaluation
    states: np.ndarray
    checkpoint_steps: list[int]
    controller_period_steps: int
    controller_invocations: int
    reference_path: list[dict[str, Any]] = field(default_factory=list)


def _set_initial_state(data: mujoco.MjData, p0: list[float]) -> None:
    data.qpos[0] = float(p0[0])
    data.qpos[1] = float(p0[1])
    data.qpos[2] = float(p0[2])
    data.qpos[3] = 1.0
    data.qpos[4] = 0.0
    data.qpos[5] = 0.0
    data.qpos[6] = 0.0


def fly(
    compiled_xml: str,
    mission: MissionSpecV2,
    world: WorldSpec,
    *,
    controller_fn: Callable[[dict[str, Any]], Any] | None = None,
    recorded_controller_actions: list[list[float]] | None = None,
    faults: MissionFaultSchedule | None = None,
    seed: int = 42,
    initial_pos_m: list[float] | None = None,
    max_wall_time_s: float | None = None,
    cancel_event: threading.Event | None = None,
    checkpoint_interval_steps: int = CHECKPOINT_INTERVAL_STEPS,
) -> FlightRun:
    if (controller_fn is None) == (recorded_controller_actions is None):
        raise ValueError("Provide exactly one of controller_fn or recorded_controller_actions")

    started = time.monotonic()
    model = mujoco.MjModel.from_xml_string(compiled_xml)
    data = mujoco.MjData(model)
    cf2_body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
    if cf2_body_id < 0:
        raise ValueError("Crazyflie body 'cf2' not found in model")

    p0 = list(initial_pos_m or [0.0, 0.0, 0.05])
    _set_initial_state(data, p0)
    mujoco.mj_forward(model, data)

    bounds = ActionBounds(
        tuple(float(x) for x in model.actuator_ctrlrange[:, 0]),
        tuple(float(x) for x in model.actuator_ctrlrange[:, 1]),
    )

    progress = MissionProgressTracker(mission)
    planner = ReferenceTrajectory(mission, initial_position_m=p0)
    injector = FaultInjector(faults, seed=seed)

    steps = mission.physics_steps
    dt = mission.physics_dt_s
    period = mission.controller_period_steps
    expected_invocations = -(-steps // period)
    if recorded_controller_actions is not None and len(recorded_controller_actions) != expected_invocations:
        raise ValueError(
            f"Recorded controller actions: expected {expected_invocations}, got {len(recorded_controller_actions)}"
        )

    trajectory: list[dict[str, Any]] = []
    step_actions: list[list[float]] = []
    controller_actions: list[list[float]] = []
    contacts: list[ContactEvent] = []
    states = np.empty((steps + 1, mujoco.mj_stateSize(model, mujoco.mjtState.mjSTATE_INTEGRATION)))
    states[0] = capture_integration_state(model, data)
    held_action: tuple[float, float, float, float] | None = None
    invocation = 0

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

        pad_contact = any(
            c.contact_class == "allowed-touchdown" and c.step_index == step_idx - 1
            for c in contacts
        )
        prog_info = progress.update(sim_time, step_idx, pos, vel, pad_contact=pad_contact, dt_s=dt)

        if step_idx % period == 0:
            if controller_fn is not None:
                ref_sample = planner.sample(sim_time)
                true_observation = {
                    "schema_version": "1.0",
                    "trial_id": f"mission-{mission.mission_id}",
                    "step_index": step_idx,
                    "sim_time_s": sim_time,
                    "dt_s": mission.controller_dt_s,
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
                validate_observation_frame(
                    true_observation,
                    expected_controller_dt_s=mission.controller_dt_s,
                    physics_dt_s=dt,
                    current_step_index=step_idx,
                )
                guest_obs = injector.apply_sensor_faults(true_observation, sim_time)
                validate_observation_frame(
                    guest_obs,
                    expected_controller_dt_s=mission.controller_dt_s,
                    physics_dt_s=dt,
                    current_step_index=step_idx,
                )
                raw_action = controller_fn(guest_obs)
                held_action = parse_action(
                    encode_action_payload(raw_action),
                    trial_id=f"mission-{mission.mission_id}",
                    step_index=step_idx,
                    bounds=bounds,
                )
            else:
                recorded = recorded_controller_actions[invocation]
                if len(recorded) != 4 or not all(
                    isinstance(v, (int, float)) and math.isfinite(v) and lo <= v <= hi
                    for v, lo, hi in zip(recorded, bounds.lower, bounds.upper)
                ):
                    raise ValueError(f"Recorded controller action {invocation} is outside actuator bounds")
                held_action = tuple(float(v) for v in recorded)
            controller_actions.append(list(held_action))
            invocation += 1

        effective_action = injector.apply_actuator_derating(held_action, sim_time)
        step_actions.append(list(held_action))
        data.ctrl[:] = effective_action
        wind_f = injector.get_applied_wind_force_n(sim_time)
        data.xfrc_applied[cf2_body_id, :3] = wind_f

        mujoco.mj_step(model, data)
        states[step_idx + 1] = capture_integration_state(model, data)

        for c_idx in range(data.ncon):
            con = data.contact[c_idx]
            g1_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, con.geom1) or f"geom_{con.geom1}"
            g2_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, con.geom2) or f"geom_{con.geom2}"
            is_cf2 = (
                model.geom_bodyid[con.geom1] == cf2_body_id
                or model.geom_bodyid[con.geom2] == cf2_body_id
                or "cf2" in g1_name
                or "cf2" in g2_name
            )
            if not is_cf2:
                continue
            impact_v = math.sqrt(vel[0] ** 2 + vel[1] ** 2 + vel[2] ** 2)
            contacts.append(
                ContactEvent(
                    step_index=step_idx,
                    sim_time_s=sim_time,
                    geom1=g1_name,
                    geom2=g2_name,
                    contact_class=classify_contact(f"{g1_name} {g2_name}".lower()),
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
            "action": list(held_action),
            "effective_action": list(effective_action),
            "wind_force_n": wind_f,
        })

    progress.finalize(float(data.time))
    evaluation = MissionSafetyMonitor.evaluate(mission, world, trajectory, contacts, progress.stage_history)

    checkpoint_steps = list(range(0, steps + 1, max(1, checkpoint_interval_steps)))
    if checkpoint_steps[-1] != steps:
        checkpoint_steps.append(steps)

    duration = mission.total_mission_duration_s
    reference_path = [
        {"sim_time_s": round(t, 6), "position_m": planner.sample(t)["position_m"]}
        for t in (duration * i / (REFERENCE_PATH_SAMPLES - 1) for i in range(REFERENCE_PATH_SAMPLES))
    ]

    return FlightRun(
        trajectory=trajectory,
        step_actions=step_actions,
        controller_actions=controller_actions,
        contacts=contacts,
        stage_history=progress.stage_history,
        evaluation=evaluation,
        states=states,
        checkpoint_steps=checkpoint_steps,
        controller_period_steps=period,
        controller_invocations=invocation,
        reference_path=reference_path,
    )


class MissionSimulationResult:
    def __init__(
        self,
        *,
        mission: MissionSpecV2,
        world: WorldSpec,
        run: FlightRun,
        compiled_xml: str,
        initial_pos_m: list[float],
        seed: int,
        replay_max_abs_diff: float,
        replay_matched: bool,
    ) -> None:
        self.mission = mission
        self.world = world
        self.run = run
        self.compiled_xml = compiled_xml
        self.initial_pos_m = initial_pos_m
        self.seed = seed
        self.trajectory = run.trajectory
        self.actions = run.step_actions
        self.controller_actions = run.controller_actions
        self.contacts = run.contacts
        self.evaluation = run.evaluation
        self.replay_max_abs_diff = replay_max_abs_diff
        self.replay_matched = replay_matched

    @property
    def controller_invocations(self) -> int:
        return self.run.controller_invocations

    @property
    def controller_period_steps(self) -> int:
        return self.run.controller_period_steps

    @property
    def effective_controller_hz(self) -> float:
        return 1.0 / (self.mission.physics_dt_s * self.run.controller_period_steps)


def run_mission_simulation(
    base_model_path: Path,
    mission: MissionSpecV2,
    world: WorldSpec,
    controller_fn: Callable[[dict[str, Any]], Any],
    *,
    fault_schedule: MissionFaultSchedule | None = None,
    faults: MissionFaultSchedule | None = None,
    seed: int = 42,
    initial_pos_m: list[float] | None = None,
    max_wall_time_s: float | None = None,
    cancel_event: threading.Event | None = None,
) -> MissionSimulationResult:
    """Execute a complete 3D mission in the trusted MuJoCo kernel, then replay it.

    ``max_wall_time_s`` and ``cancel_event`` are checked before every physics
    step; when either trips, the run stops with ``MissionWallTimeExceededError``
    or ``MissionCancelledError`` and no partial verdict is produced. The caller
    owns any guest resources and must tear them down.
    """
    effective_faults = fault_schedule if fault_schedule is not None else faults
    p0 = list(initial_pos_m or [0.0, 0.0, 0.05])
    compiled_xml = compile_world_xml(base_model_path, world)

    run = fly(
        compiled_xml,
        mission,
        world,
        controller_fn=controller_fn,
        faults=effective_faults,
        seed=seed,
        initial_pos_m=p0,
        max_wall_time_s=max_wall_time_s,
        cancel_event=cancel_event,
    )

    # Independent replay of the recorded actions on a fresh model instance.
    replay = fly(
        compiled_xml,
        mission,
        world,
        recorded_controller_actions=run.controller_actions,
        faults=effective_faults,
        seed=seed,
        initial_pos_m=p0,
    )
    max_diff = float(np.max(np.abs(run.states - replay.states)))

    return MissionSimulationResult(
        mission=mission,
        world=world,
        run=run,
        compiled_xml=compiled_xml,
        initial_pos_m=p0,
        seed=seed,
        replay_max_abs_diff=max_diff,
        replay_matched=max_diff <= REPLAY_TOLERANCE,
    )

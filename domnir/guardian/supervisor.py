"""Trusted Runtime Guardian and Safety Supervisor for Bitcraze Crazyflie 2.

This module implements Simplex-style runtime assurance and safety shielding
for Crazyflie flight controllers, monitoring kinematic state barriers and
overriding control actions before they reach the plant.
"""

from __future__ import annotations

from enum import Enum
import math
from pathlib import Path
from typing import Any, Callable, Sequence
import numpy as np
from pydantic import BaseModel, Field

from domnir.contracts.stl import SafetyContract, STLMonitor, STLRobustnessResult
from domnir.spec import GeneratedController
from domnir.uncertainty.simulator import normalize_action_vector, resolve_model_path

try:
    import mujoco
    HAS_MUJOCO = True
except ImportError:
    HAS_MUJOCO = False


class InterventionCause(str, Enum):
    FLOOR_BREACH = "FLOOR_BREACH"
    CEILING_BREACH = "CEILING_BREACH"
    TILT_EXCESS = "TILT_EXCESS"
    VELOCITY_EXCESS = "VELOCITY_EXCESS"
    NONE = "NONE"


class FeasibilityStatus(str, Enum):
    FEASIBLE = "FEASIBLE"
    INFEASIBLE_SATURATED = "INFEASIBLE_SATURATED"
    INFEASIBLE_INERTIA = "INFEASIBLE_INERTIA"


class InterventionRecord(BaseModel):
    step_index: int
    timestamp_s: float
    requested_action: list[float]
    applied_action: list[float]
    cause: InterventionCause
    feasibility: FeasibilityStatus
    predicted_state: dict[str, float]
    reason: str


class GuardianTrialReport(BaseModel):
    unshielded_robustness: float
    unshielded_verdict: str
    shielded_robustness: float
    shielded_verdict: str
    interventions_count: int
    interventions_timeline: list[InterventionRecord] = Field(default_factory=list)
    infeasible_interventions_count: int = 0
    summary: str = ""

    @property
    def shielded_satisfied(self) -> bool:
        return self.shielded_robustness >= 0.0

    @property
    def unshielded_satisfied(self) -> bool:
        return self.unshielded_robustness >= 0.0


def _resolve_controller_fn(controller: Any) -> Callable[[dict[str, Any]], Any]:
    if hasattr(controller, "observe") and callable(controller.observe):
        return controller.observe
    if callable(controller):
        return controller
    if isinstance(controller, (GeneratedController, str)):
        source_code = controller.source_code if isinstance(controller, GeneratedController) else controller
        from domnir.evaluator import get_builtin_controller_fn
        builtin_fn = get_builtin_controller_fn(source_code)
        if builtin_fn is not None:
            return builtin_fn

        from domnir.evaluator import SafeControllerEvaluator, is_microvm_available
        if not SafeControllerEvaluator.is_execution_available():
            raise RuntimeError(
                "BLOCKED: ISOLATION_UNAVAILABLE: MicroVM hardware acceleration (/dev/kvm) is required to execute untrusted controller code."
            )
        from domnir.api.jobs import _MicroVMGuestStream, _IsolatedSubprocessGuestStream
        from domnir.sandbox import SandboxLease
        import shutil
        import json
        if is_microvm_available():
            msb_path = Path(os.environ.get("DOMNIR_MSB") or shutil.which("msb"))
            lease = SandboxLease(msb_path, duration_seconds=60)
            lease.__enter__()
            lease.install_controller(source_code.encode("utf-8"))
            stream = _MicroVMGuestStream(lease)
        else:
            stream = _IsolatedSubprocessGuestStream(source_code)

        def sandboxed_observe(obs: dict[str, Any]) -> Any:
            resp_str = stream.exchange(obs)
            return json.loads(resp_str)

        return sandboxed_observe
    raise ValueError(f"Unsupported controller type: {type(controller)}")


def _resolve_scenario_params(
    scenario: Any, default_altitude: float
) -> tuple[float, float, float, float]:
    if scenario is None:
        return default_altitude, 0.0, 0.0, 0.0
    if isinstance(scenario, dict):
        init_z = float(scenario.get("initial_altitude_m", default_altitude))
        dist_f = float(scenario.get("disturbance_force_z", 0.0))
        p_start = float(scenario.get("pulse_start_s", 0.0))
        p_dur = float(scenario.get("pulse_duration_s", 0.0))
        return init_z, dist_f, p_start, p_dur
    init_z = float(getattr(scenario, "initial_altitude_m", default_altitude))
    dist_f = float(getattr(scenario, "disturbance_force_z", 0.0))
    p_start = float(getattr(scenario, "pulse_start_s", 0.0))
    p_dur = float(getattr(scenario, "pulse_duration_s", 0.0))
    return init_z, dist_f, p_start, p_dur


class GuardianSupervisor:
    """Runtime safety supervisor and action shielding kernel for Crazyflie 2."""

    def __init__(
        self,
        contract: SafetyContract | None = None,
        *,
        min_allowed_altitude_m: float | None = None,
        max_allowed_altitude_m: float | None = None,
        target_altitude_m: float | None = None,
        max_tilt_deg: float | None = None,
        max_velocity_mps: float | None = None,
        dt_s: float | None = None,
        mass_kg: float = 0.027,
        max_thrust_n: float = 0.35,
        min_thrust_n: float = 0.0,
        gravity_mps2: float = 9.81,
        altitude_margin_m: float = 0.02,
        tilt_margin_deg: float = 5.0,
        velocity_margin_mps: float = 0.5,
    ) -> None:
        self.contract = contract or SafetyContract()
        self.min_allowed_altitude_m = float(
            min_allowed_altitude_m
            if min_allowed_altitude_m is not None
            else self.contract.min_allowed_altitude_m
        )
        self.max_allowed_altitude_m = float(
            max_allowed_altitude_m
            if max_allowed_altitude_m is not None
            else self.contract.max_allowed_altitude_m
        )
        self.target_altitude_m = float(
            target_altitude_m
            if target_altitude_m is not None
            else self.contract.target_altitude_m
        )
        self.max_tilt_deg = float(
            max_tilt_deg
            if max_tilt_deg is not None
            else self.contract.max_tilt_deg
        )
        self.max_velocity_mps = float(
            max_velocity_mps
            if max_velocity_mps is not None
            else self.contract.max_velocity_mps
        )
        self.dt_s = float(
            dt_s if dt_s is not None else self.contract.physics_dt_s
        )
        self.mass_kg = float(mass_kg)
        self.max_thrust_n = float(max_thrust_n)
        self.min_thrust_n = float(min_thrust_n)
        self.gravity_mps2 = float(gravity_mps2)
        self.altitude_margin_m = float(altitude_margin_m)
        self.tilt_margin_deg = float(tilt_margin_deg)
        self.velocity_margin_mps = float(velocity_margin_mps)
        self.history: list[InterventionRecord] = []

    def reset(self) -> None:
        self.history.clear()

    def _extract_thrust(
        self, action: list[float] | Sequence[float] | dict[str, Any]
    ) -> float:
        if isinstance(action, dict):
            return float(action.get("thrust", 0.0))
        if not isinstance(action, (list, tuple, np.ndarray)) or len(action) == 0:
            return 0.0
        vals = [float(x) for x in action]
        if len(vals) == 1:
            return vals[0]
        if len(vals) == 4:
            # Check whether action represents 4 individual rotor forces
            per_rotor_max = (self.max_thrust_n / 4.0) + 0.03
            if all(0.0 <= x <= per_rotor_max for x in vals) and any(
                x > 0.001 for x in vals[1:]
            ):
                return float(sum(vals))
            return vals[0]
        return vals[0]

    def _to_list(
        self, action: list[float] | Sequence[float] | dict[str, Any]
    ) -> list[float]:
        if isinstance(action, dict):
            return [
                float(action.get("thrust", 0.0)),
                float(action.get("moment_x", 0.0)),
                float(action.get("moment_y", 0.0)),
                float(action.get("moment_z", 0.0)),
            ]
        if isinstance(action, (list, tuple, np.ndarray)):
            return [float(x) for x in action]
        return [float(action)]

    def _create_shielded_action(
        self,
        requested_action: list[float] | Sequence[float] | dict[str, Any],
        thrust: float,
        *,
        level_attitude: bool = True,
    ) -> list[float]:
        clamped_thrust = max(self.min_thrust_n, min(self.max_thrust_n, float(thrust)))
        if isinstance(requested_action, dict):
            mx = 0.0 if level_attitude else float(requested_action.get("moment_x", 0.0))
            my = 0.0 if level_attitude else float(requested_action.get("moment_y", 0.0))
            mz = 0.0 if level_attitude else float(requested_action.get("moment_z", 0.0))
            return [clamped_thrust, mx, my, mz]

        if not isinstance(requested_action, (list, tuple, np.ndarray)) or len(requested_action) == 0:
            return [clamped_thrust, 0.0, 0.0, 0.0]

        vals = [float(x) for x in requested_action]
        if len(vals) == 1:
            return [clamped_thrust]

        if len(vals) == 4:
            per_rotor_max = (self.max_thrust_n / 4.0) + 0.03
            if all(0.0 <= x <= per_rotor_max for x in vals) and any(
                x > 0.001 for x in vals[1:]
            ):
                if level_attitude:
                    return [clamped_thrust / 4.0] * 4
                cur_sum = sum(vals)
                if cur_sum > 1e-6:
                    scale = clamped_thrust / cur_sum
                    return [x * scale for x in vals]
                return [clamped_thrust / 4.0] * 4

            mx = 0.0 if level_attitude else vals[1]
            my = 0.0 if level_attitude else vals[2]
            mz = 0.0 if level_attitude else vals[3]
            return [clamped_thrust, mx, my, mz]

        if level_attitude:
            res = [0.0] * len(vals)
            res[0] = clamped_thrust
            return res

        res = list(vals)
        res[0] = clamped_thrust
        return res

    def inspect_and_shield(
        self,
        observation: dict[str, Any],
        requested_action: list[float] | Sequence[float] | dict[str, Any],
        step_index: int = 0,
    ) -> tuple[list[float], InterventionRecord | None]:
        req_list = self._to_list(requested_action)
        thrust_requested = self._extract_thrust(requested_action)

        dt = float(observation.get("dt_s", self.dt_s))
        sim_time = float(observation.get("sim_time_s", step_index * dt))

        pos = observation.get("position_m", [0.0, 0.0, self.target_altitude_m])
        z = float(pos[2]) if len(pos) > 2 else self.target_altitude_m

        vel = observation.get("velocity_mps", [0.0, 0.0, 0.0])
        vz = float(vel[2]) if len(vel) > 2 else 0.0
        speed = math.sqrt(sum(float(v) ** 2 for v in vel[:3]))

        quat = observation.get("orientation_quat_wxyz", [1.0, 0.0, 0.0, 0.0])
        tilt_rad = STLMonitor.calculate_tilt_rad(quat)
        tilt_deg = math.degrees(tilt_rad)

        # 1-step vertical kinematics under requested thrust
        az_req = (thrust_requested / self.mass_kg) - self.gravity_mps2
        z_next = z + vz * dt + 0.5 * az_req * (dt ** 2)
        vz_next = vz + az_req * dt

        predicted_state = {
            "altitude_m": float(z_next),
            "velocity_z_mps": float(vz_next),
            "predicted_z": float(z_next),
            "tilt_deg": float(tilt_deg),
        }

        # Kinematic acceleration bounds
        a_z_max = (self.max_thrust_n / self.mass_kg) - self.gravity_mps2
        a_z_min = (self.min_thrust_n / self.mass_kg) - self.gravity_mps2

        # Stopping distance calculations
        if vz < 0.0:
            if a_z_max > 0.0:
                d_stop_down = (vz ** 2) / (2.0 * a_z_max)
            else:
                d_stop_down = float("inf")
        else:
            d_stop_down = 0.0

        if vz > 0.0:
            d_stop_up = (vz ** 2) / (2.0 * abs(a_z_min))
        else:
            d_stop_up = 0.0

        avail_alt_down = z - self.min_allowed_altitude_m
        avail_alt_up = self.max_allowed_altitude_m - z

        # Condition 1: Floor breach check
        floor_limit = self.min_allowed_altitude_m + self.altitude_margin_m
        floor_breach = (
            z_next <= floor_limit
            or (z - d_stop_down) <= floor_limit
            or z <= self.min_allowed_altitude_m
        )

        if floor_breach:
            cause = InterventionCause.FLOOR_BREACH
            if a_z_max <= 0.0:
                feasibility = FeasibilityStatus.INFEASIBLE_SATURATED
                reason = (
                    f"Floor breach predicted (z_next={z_next:.4f}m <= {floor_limit:.4f}m). "
                    "Max upward thrust cannot overcome gravity."
                )
            elif d_stop_down > max(0.0, avail_alt_down):
                feasibility = FeasibilityStatus.INFEASIBLE_INERTIA
                reason = (
                    f"Floor breach predicted (z_next={z_next:.4f}m <= {floor_limit:.4f}m). "
                    f"Downward stopping distance ({d_stop_down:.4f}m) exceeds available altitude "
                    f"({avail_alt_down:.4f}m) under max thrust."
                )
            else:
                feasibility = FeasibilityStatus.FEASIBLE
                reason = (
                    f"Floor breach predicted (z_next={z_next:.4f}m <= {floor_limit:.4f}m). "
                    "Overriding thrust to maximum upward thrust."
                )

            applied_action = self._create_shielded_action(
                requested_action, self.max_thrust_n, level_attitude=True
            )
            record = InterventionRecord(
                step_index=step_index,
                timestamp_s=sim_time,
                requested_action=req_list,
                applied_action=applied_action,
                cause=cause,
                feasibility=feasibility,
                predicted_state=predicted_state,
                reason=reason,
            )
            self.history.append(record)
            return applied_action, record

        # Condition 2: Ceiling breach check
        ceiling_limit = self.max_allowed_altitude_m - self.altitude_margin_m
        ceiling_breach = (
            z_next >= ceiling_limit
            or (z + d_stop_up) >= ceiling_limit
            or z >= self.max_allowed_altitude_m
        )

        if ceiling_breach:
            cause = InterventionCause.CEILING_BREACH
            if d_stop_up > max(0.0, avail_alt_up):
                feasibility = FeasibilityStatus.INFEASIBLE_INERTIA
                reason = (
                    f"Ceiling breach predicted (z_next={z_next:.4f}m >= {ceiling_limit:.4f}m). "
                    f"Upward stopping distance ({d_stop_up:.4f}m) exceeds ceiling clearance "
                    f"({avail_alt_up:.4f}m) under idle thrust."
                )
            else:
                feasibility = FeasibilityStatus.FEASIBLE
                reason = (
                    f"Ceiling breach predicted (z_next={z_next:.4f}m >= {ceiling_limit:.4f}m). "
                    "Cutting thrust to idle."
                )

            applied_action = self._create_shielded_action(
                requested_action, self.min_thrust_n, level_attitude=True
            )
            record = InterventionRecord(
                step_index=step_index,
                timestamp_s=sim_time,
                requested_action=req_list,
                applied_action=applied_action,
                cause=cause,
                feasibility=feasibility,
                predicted_state=predicted_state,
                reason=reason,
            )
            self.history.append(record)
            return applied_action, record

        # Condition 3: Attitude tilt check
        tilt_limit = self.max_tilt_deg - self.tilt_margin_deg
        if tilt_deg >= tilt_limit:
            cause = InterventionCause.TILT_EXCESS
            feasibility = FeasibilityStatus.FEASIBLE
            reason = (
                f"Tilt approaching limit (tilt={tilt_deg:.2f} deg >= {tilt_limit:.2f} deg). "
                "Leveling differential attitude commands."
            )
            applied_action = self._create_shielded_action(
                requested_action, thrust_requested, level_attitude=True
            )
            record = InterventionRecord(
                step_index=step_index,
                timestamp_s=sim_time,
                requested_action=req_list,
                applied_action=applied_action,
                cause=cause,
                feasibility=feasibility,
                predicted_state=predicted_state,
                reason=reason,
            )
            self.history.append(record)
            return applied_action, record

        # Condition 4: Velocity magnitude check
        vel_limit = self.max_velocity_mps - self.velocity_margin_mps
        if speed >= vel_limit:
            cause = InterventionCause.VELOCITY_EXCESS
            feasibility = FeasibilityStatus.FEASIBLE
            override_t = self.max_thrust_n if vz < 0 else self.min_thrust_n
            reason = (
                f"Velocity approaching limit (speed={speed:.2f} m/s >= {vel_limit:.2f} m/s). "
                "Shielding velocity vector."
            )
            applied_action = self._create_shielded_action(
                requested_action, override_t, level_attitude=True
            )
            record = InterventionRecord(
                step_index=step_index,
                timestamp_s=sim_time,
                requested_action=req_list,
                applied_action=applied_action,
                cause=cause,
                feasibility=feasibility,
                predicted_state=predicted_state,
                reason=reason,
            )
            self.history.append(record)
            return applied_action, record

        # Safe state, no intervention needed
        return req_list, None


class GuardianTrialComparator:
    """Evaluates controllers across scenarios in unshielded and shielded modes."""

    def __init__(
        self,
        contract: SafetyContract | None = None,
        supervisor: GuardianSupervisor | None = None,
        *,
        model_path: Path | str | None = None,
        use_mujoco: bool = True,
    ) -> None:
        self.contract = contract or SafetyContract()
        self.supervisor = supervisor or GuardianSupervisor(self.contract)
        resolved = resolve_model_path(model_path) if (model_path is not None or resolve_model_path().is_file()) else None
        self.model_path = resolved if (resolved is not None and resolved.is_file()) else None
        self.use_mujoco = bool(use_mujoco and HAS_MUJOCO and self.model_path is not None)

    def _simulate_flight(
        self,
        controller_fn: Callable[[dict[str, Any]], Any],
        scenario: Any,
        steps: int,
        trial_id: str,
        shielded: bool,
    ) -> tuple[list[dict[str, Any]], list[InterventionRecord]]:
        init_z, dist_f, pulse_start, pulse_dur = _resolve_scenario_params(
            scenario, self.contract.target_altitude_m
        )

        if self.use_mujoco and self.model_path is not None:
            model = mujoco.MjModel.from_xml_path(str(self.model_path))
            data = mujoco.MjData(model)
            body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
            data.qpos[2] = init_z
            mujoco.mj_forward(model, data)
            dt = float(model.opt.timestep)

            trajectory: list[dict[str, Any]] = []
            interventions: list[InterventionRecord] = []

            for step_idx in range(steps):
                sim_time = float(data.time)
                pos = data.qpos[:3].tolist()
                vel = data.qvel[:3].tolist()
                quat = data.qpos[3:7].tolist()
                ang_vel = data.qvel[3:6].tolist()

                trajectory.append({
                    "step_index": step_idx,
                    "sim_time_s": sim_time,
                    "position_m": pos,
                    "velocity_mps": vel,
                    "orientation_quat_wxyz": quat,
                    "body_angular_velocity_rps": ang_vel,
                })

                obs = {
                    "schema_version": "1.0",
                    "trial_id": trial_id,
                    "step_index": step_idx,
                    "sim_time_s": sim_time,
                    "dt_s": dt,
                    "position_m": pos,
                    "velocity_mps": vel,
                    "orientation_quat_wxyz": quat,
                    "body_angular_velocity_rps": ang_vel,
                    "target_position_m": [0.0, 0.0, self.contract.target_altitude_m],
                    "target_altitude_m": self.contract.target_altitude_m,
                }

                raw_action = controller_fn(obs)

                if shielded:
                    applied_action, record = self.supervisor.inspect_and_shield(
                        obs, raw_action, step_idx
                    )
                    if record is not None:
                        interventions.append(record)
                else:
                    applied_action = raw_action

                ctrl_vec = normalize_action_vector(applied_action, model.nu)
                ctrl_min = model.actuator_ctrlrange[:, 0]
                ctrl_max = model.actuator_ctrlrange[:, 1]
                data.ctrl[:] = np.clip(ctrl_vec, ctrl_min, ctrl_max)

                if body_id >= 0:
                    if scenario is not None and hasattr(scenario, "pulse_start_s"):
                        from domnir.scenario import calculate_applied_disturbance
                        current_disturbance = calculate_applied_disturbance(scenario, sim_time)
                    elif pulse_dur > 0.0:
                        current_disturbance = dist_f if pulse_start <= sim_time < pulse_start + pulse_dur else 0.0
                    else:
                        current_disturbance = dist_f
                    data.xfrc_applied[body_id, 2] = current_disturbance

                mujoco.mj_step(model, data)

            trajectory.append({
                "step_index": steps,
                "sim_time_s": float(data.time),
                "position_m": data.qpos[:3].tolist(),
                "velocity_mps": data.qvel[:3].tolist(),
                "orientation_quat_wxyz": data.qpos[3:7].tolist(),
                "body_angular_velocity_rps": data.qvel[3:6].tolist(),
            })
            return trajectory, interventions

        # Analytical simulation fallback
        dt = self.contract.physics_dt_s
        z = init_z
        vz = 0.0
        trajectory = []
        interventions = []

        for step_idx in range(steps):
            sim_time = step_idx * dt
            pos = [0.0, 0.0, z]
            vel = [0.0, 0.0, vz]
            quat = [1.0, 0.0, 0.0, 0.0]

            trajectory.append({
                "step_index": step_idx,
                "sim_time_s": sim_time,
                "position_m": pos,
                "velocity_mps": vel,
                "orientation_quat_wxyz": quat,
                "body_angular_velocity_rps": [0.0, 0.0, 0.0],
            })

            obs = {
                "schema_version": "1.0",
                "trial_id": trial_id,
                "step_index": step_idx,
                "sim_time_s": sim_time,
                "dt_s": dt,
                "position_m": pos,
                "velocity_mps": vel,
                "orientation_quat_wxyz": quat,
                "body_angular_velocity_rps": [0.0, 0.0, 0.0],
                "target_position_m": [0.0, 0.0, self.contract.target_altitude_m],
                "target_altitude_m": self.contract.target_altitude_m,
            }

            raw_action = controller_fn(obs)

            if shielded:
                applied_action, record = self.supervisor.inspect_and_shield(
                    obs, raw_action, step_idx
                )
                if record is not None:
                    interventions.append(record)
            else:
                applied_action = raw_action

            thrust = self.supervisor._extract_thrust(applied_action)
            if scenario is not None and hasattr(scenario, "pulse_start_s"):
                from domnir.scenario import calculate_applied_disturbance
                current_disturbance = calculate_applied_disturbance(scenario, sim_time)
            elif pulse_dur > 0.0:
                current_disturbance = dist_f if pulse_start <= sim_time < pulse_start + pulse_dur else 0.0
            else:
                current_disturbance = dist_f

            az = (
                (thrust / self.supervisor.mass_kg)
                - self.supervisor.gravity_mps2
                + (current_disturbance / self.supervisor.mass_kg)
            )
            vz += az * dt
            z += vz * dt + 0.5 * az * (dt ** 2)
            z = max(0.0, z)

        trajectory.append({
            "step_index": steps,
            "sim_time_s": steps * dt,
            "position_m": [0.0, 0.0, z],
            "velocity_mps": [0.0, 0.0, vz],
            "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
            "body_angular_velocity_rps": [0.0, 0.0, 0.0],
        })
        return trajectory, interventions

    def compare(
        self,
        controller: Any,
        scenario: Any = None,
        *,
        steps: int | None = None,
        trial_id: str = "guardian_trial",
    ) -> GuardianTrialReport:
        controller_fn = _resolve_controller_fn(controller)
        num_steps = steps if steps is not None else self.contract.physics_steps

        # Reset supervisor history before evaluation
        self.supervisor.reset()

        # 1. Unshielded run: original controller alone
        unshielded_traj, _ = self._simulate_flight(
            controller_fn, scenario, num_steps, trial_id=f"{trial_id}_unshielded", shielded=False
        )
        unshielded_res = STLMonitor.evaluate_trajectory(self.contract, unshielded_traj)

        # Reset supervisor history before shielded run
        self.supervisor.reset()

        # 2. Shielded run: Guardian in the loop
        shielded_traj, interventions = self._simulate_flight(
            controller_fn, scenario, num_steps, trial_id=f"{trial_id}_shielded", shielded=True
        )
        shielded_res = STLMonitor.evaluate_trajectory(self.contract, shielded_traj)

        unshielded_robustness = float(unshielded_res.min_robustness)
        unshielded_verdict = unshielded_res.verdict

        shielded_robustness = float(shielded_res.min_robustness)
        if shielded_res.satisfied:
            shielded_verdict = "GUARDIAN_INTERVENED" if len(interventions) > 0 else "SATISFIED"
        else:
            shielded_verdict = "VIOLATED"

        interventions_count = len(interventions)
        infeasible_count = sum(
            1 for rec in interventions if rec.feasibility != FeasibilityStatus.FEASIBLE
        )

        summary = (
            f"Controller unshielded verdict: {unshielded_verdict} (robustness: {unshielded_robustness:+.4f}). "
            f"Shielded verdict: {shielded_verdict} (robustness: {shielded_robustness:+.4f}) "
            f"with {interventions_count} interventions ({infeasible_count} infeasible). "
            "Original controller safety finding is preserved without masking."
        )

        return GuardianTrialReport(
            unshielded_robustness=unshielded_robustness,
            unshielded_verdict=unshielded_verdict,
            shielded_robustness=shielded_robustness,
            shielded_verdict=shielded_verdict,
            interventions_count=interventions_count,
            interventions_timeline=interventions,
            infeasible_interventions_count=infeasible_count,
            summary=summary,
        )

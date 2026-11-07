"""Safe typed execution adapter for untrusted flight controllers.

Untrusted controller Python source code from LLMs, API requests, Court Records,
CI invocations, or benchmarks must NEVER be executed directly on the host process.
This module enforces isolation boundaries:
1. Untrusted source must execute inside an approved microVM sandbox (Linux /dev/kvm).
2. Development fallback (isolated subprocess) is only permitted when explicitly enabled
   via DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK=1 outside of production.
3. When virtualization is unavailable, execution fails closed (UNAVAILABLE).
4. Trusted in-memory callables (unit test fixtures) are handled through an explicit
   trusted harness with documented trust assumptions.
"""

from __future__ import annotations

import ast
import os
import shutil
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from pydantic import BaseModel, Field

from domnir.contracts.stl import SafetyContract
from domnir.scenario import ScenarioParameter


class ExecutionBackend(str, Enum):
    MICROVM = "microvm"
    SUBPROCESS_DEV = "subprocess_dev_unisolated"
    TRUSTED_HARNESS = "trusted_harness"
    STATIC_ANALYSIS = "static_analysis_only"


class ControllerExecutionResult(BaseModel):
    status: str  # "SUCCESS", "UNAVAILABLE", "ERROR", "TIMEOUT"
    backend: ExecutionBackend
    trajectory: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[list[float]] = Field(default_factory=list)
    states: list[list[float]] = Field(default_factory=list)
    error_message: str | None = None


def is_microvm_available() -> bool:
    """Check if Microsandbox binary and /dev/kvm hardware acceleration are present."""
    msb_bin = os.environ.get("DOMNIR_MSB") or shutil.which("msb")
    kvm_accessible = os.path.exists("/dev/kvm") and os.access("/dev/kvm", os.R_OK | os.W_OK)
    return bool(msb_bin and kvm_accessible)


def _builtin_open_loop_weak(obs: dict[str, Any]) -> list[float]:
    return [0.18, 0.18, 0.18, 0.18]


def _builtin_classical_p(obs: dict[str, Any]) -> list[float]:
    pos = obs.get("position_m", [0.0, 0.0, 0.0])
    target_z = obs.get("target_altitude_m", 0.10)
    err = target_z - pos[2]
    thrust = max(0.0, min(1.0, 0.27 + 2.0 * err))
    return [thrust, thrust, thrust, thrust]


def _builtin_calibrated_pid(obs: dict[str, Any]) -> list[float]:
    pos = obs.get("position_m", [0.0, 0.0, 0.0])
    vel = obs.get("velocity_mps", [0.0, 0.0, 0.0])
    target_z = obs.get("target_altitude_m", 0.10)
    err = target_z - pos[2]
    vz = vel[2]
    thrust = max(0.0, min(1.0, 0.27 + 3.2 * err - 0.45 * vz))
    return [thrust, thrust, thrust, thrust]


def _builtin_overthrust_runaway(obs: dict[str, Any]) -> list[float]:
    return [0.95, 0.95, 0.95, 0.95]


def _normalize_src(src: str) -> str:
    return "".join(src.split())


_BUILTIN_REGISTRY: list[tuple[str, Callable[[dict[str, Any]], list[float]]]] = [
    (
        "def observe(observation: dict) -> list[float]: return [0.18, 0.18, 0.18, 0.18]",
        _builtin_open_loop_weak,
    ),
    (
        "def observe(observation: dict) -> list[float]: pos = observation.get('position_m', [0.0, 0.0, 0.0]) target_z = observation.get('target_altitude_m', 0.10) err = target_z - pos[2] thrust = max(0.0, min(1.0, 0.27 + 2.0 * err)) return [thrust, thrust, thrust, thrust]",
        _builtin_classical_p,
    ),
    (
        "def observe(observation: dict) -> list[float]: pos = observation.get('position_m', [0.0, 0.0, 0.0]) vel = observation.get('velocity_mps', [0.0, 0.0, 0.0]) target_z = observation.get('target_altitude_m', 0.10) err = target_z - pos[2] vz = vel[2] thrust = max(0.0, min(1.0, 0.27 + 3.2 * err - 0.45 * vz)) return [thrust, thrust, thrust, thrust]",
        _builtin_calibrated_pid,
    ),
    (
        "def observe(observation: dict) -> list[float]: return [0.95, 0.95, 0.95, 0.95]",
        _builtin_overthrust_runaway,
    ),
]


def get_builtin_controller_fn(source_code: str) -> Callable[[dict[str, Any]], list[float]] | None:
    """Return trusted in-memory callable for known built-in reference controllers."""
    if not source_code:
        return None
    # Strip comments and whitespace
    clean_lines = [
        line.split("#")[0].strip()
        for line in source_code.splitlines()
        if line.split("#")[0].strip()
    ]
    norm = " ".join(clean_lines)
    for pattern, fn in _BUILTIN_REGISTRY:
        if norm == pattern:
            return fn
    return None


def validate_controller_source(source: str) -> None:
    """Statically validate controller source code on host without executing it."""
    if not source or not isinstance(source, str):
        raise ValueError("Controller source code must be a non-empty string")

    source_bytes = source.encode("utf-8")
    if len(source_bytes) > 32768:
        raise ValueError(f"Controller source code exceeds 32 KiB limit ({len(source_bytes)} bytes)")

    if b"\x00" in source_bytes:
        raise ValueError("Controller source code contains null bytes")

    try:
        tree = ast.parse(source, filename="<controller>")
    except SyntaxError as err:
        raise ValueError(f"Controller syntax error: {err}") from err

    has_observe = any(
        isinstance(node, ast.FunctionDef) and node.name == "observe"
        for node in tree.body
    )
    if not has_observe:
        raise ValueError("Controller does not define a top-level 'observe' function")


class SafeControllerEvaluator:
    """Universal controller evaluator enforcing sandbox containment boundaries."""

    @staticmethod
    def is_execution_available() -> bool:
        if is_microvm_available():
            return True
        is_prod = os.environ.get("DOMNIR_ENV", os.environ.get("ENV", "")).lower() in {"production", "prod", "live"}
        dev_fallback = (not is_prod) and (os.environ.get("DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK") == "1")
        return dev_fallback

    @classmethod
    def get_available_backend(cls) -> ExecutionBackend:
        if is_microvm_available():
            return ExecutionBackend.MICROVM
        is_prod = os.environ.get("DOMNIR_ENV", os.environ.get("ENV", "")).lower() in {"production", "prod", "live"}
        if (not is_prod) and (os.environ.get("DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK") == "1"):
            return ExecutionBackend.SUBPROCESS_DEV
        return ExecutionBackend.STATIC_ANALYSIS

    @classmethod
    def execute(
        cls,
        source_code: str,
        *,
        model_path: Path,
        contract: SafetyContract,
        scenario: ScenarioParameter,
    ) -> ControllerExecutionResult:
        """Execute an untrusted controller strictly within an approved sandbox."""
        # 1. Host-side static verification (safe AST parsing, no code execution)
        validate_controller_source(source_code)

        backend = cls.get_available_backend()
        if backend == ExecutionBackend.STATIC_ANALYSIS:
            return ControllerExecutionResult(
                status="UNAVAILABLE",
                backend=ExecutionBackend.STATIC_ANALYSIS,
                error_message=(
                    "MicroVM hardware acceleration (/dev/kvm) is required to execute untrusted "
                    "controller code. Execution is strictly blocked on unvirtualized hosts."
                ),
            )

        # 2. Execution via isolated guest stream
        from domnir.api.jobs import (
            ActionBounds,
            _MicroVMGuestStream,
            _IsolatedSubprocessGuestStream,
            parse_action,
        )
        from domnir.sandbox import SandboxLease
        from domnir.scenario import calculate_applied_disturbance
        import mujoco
        import numpy as np

        model = mujoco.MjModel.from_xml_path(str(model_path))
        body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
        bounds = ActionBounds(
            tuple(float(x) for x in model.actuator_ctrlrange[:, 0]),
            tuple(float(x) for x in model.actuator_ctrlrange[:, 1]),
        )
        data = mujoco.MjData(model)
        data.qpos[2] = float(scenario.initial_altitude_m)
        mujoco.mj_forward(model, data)

        steps = contract.physics_steps
        stream: Any = None
        lease: SandboxLease | None = None

        try:
            if backend == ExecutionBackend.MICROVM:
                msb_path = Path(os.environ.get("DOMNIR_MSB") or shutil.which("msb"))
                lease = SandboxLease(msb_path, duration_seconds=60)
                lease.__enter__()
                lease.install_controller(source_code.encode("utf-8"))
                stream = _MicroVMGuestStream(lease)
            else:
                stream = _IsolatedSubprocessGuestStream(source_code)

            trajectory: list[dict[str, Any]] = [{
                "step_index": 0,
                "sim_time_s": 0.0,
                "position_m": data.qpos[:3].tolist(),
                "velocity_mps": data.qvel[:3].tolist(),
                "orientation_quat_wxyz": data.qpos[3:7].tolist(),
                "altitude_error_m": float(data.qpos[2] - contract.target_altitude_m),
                "action": [0.0, 0.0, 0.0, 0.0],
                "applied_disturbance_n": 0.0,
            }]

            recorded_actions: list[list[float]] = []
            recorded_states: list[list[float]] = [np.concatenate((data.qpos, data.qvel)).tolist()]

            for step_idx in range(steps):
                sim_time = float(data.time)
                observation = {
                    "schema_version": "1.0",
                    "trial_id": "evaluator-run",
                    "step_index": step_idx,
                    "sim_time_s": sim_time,
                    "dt_s": float(model.opt.timestep),
                    "position_m": data.qpos[:3].tolist(),
                    "velocity_mps": data.qvel[:3].tolist(),
                    "orientation_quat_wxyz": data.qpos[3:7].tolist(),
                    "body_angular_velocity_rps": data.qvel[3:6].tolist(),
                    "target_position_m": [0.0, 0.0, float(contract.target_altitude_m)],
                    "target_altitude_m": float(contract.target_altitude_m),
                }

                resp_str = stream.exchange(observation)
                action = parse_action(
                    resp_str.encode("utf-8"),
                    trial_id="evaluator-run",
                    step_index=step_idx,
                    bounds=bounds,
                )

                f_z = calculate_applied_disturbance(scenario, sim_time)
                data.ctrl[:] = action
                data.xfrc_applied[body_id, 2] = f_z
                mujoco.mj_step(model, data)

                recorded_actions.append(list(action))
                state_vec = np.concatenate((data.qpos, data.qvel))
                recorded_states.append(state_vec.tolist())

                trajectory.append({
                    "step_index": step_idx + 1,
                    "sim_time_s": float(data.time),
                    "position_m": data.qpos[:3].tolist(),
                    "velocity_mps": data.qvel[:3].tolist(),
                    "orientation_quat_wxyz": data.qpos[3:7].tolist(),
                    "altitude_error_m": float(data.qpos[2] - contract.target_altitude_m),
                    "action": list(action),
                    "applied_disturbance_n": float(f_z),
                })

                if not np.isfinite(state_vec).all():
                    break

            return ControllerExecutionResult(
                status="SUCCESS",
                backend=backend,
                trajectory=trajectory,
                actions=recorded_actions,
                states=recorded_states,
            )
        except Exception as err:
            return ControllerExecutionResult(
                status="ERROR",
                backend=backend,
                error_message=str(err),
            )
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            if lease is not None:
                try:
                    lease.remove()
                except Exception:
                    pass


class TrustedHarnessEvaluator:
    """Explicit trusted in-memory harness for pre-compiled test fixture callables.

    TRUST ASSUMPTION: This harness only accepts pre-instantiated Python callables
    written directly by developers in tests (e.g. mock hover controllers).
    Untrusted code strings or LLM-generated code MUST NEVER be passed here.
    """

    @classmethod
    def evaluate(
        cls,
        observe_fn: Callable[[dict[str, Any]], Any],
        *,
        model_path: Path,
        contract: SafetyContract,
        scenario: ScenarioParameter,
    ) -> ControllerExecutionResult:
        if not callable(observe_fn):
            raise TypeError("TrustedHarnessEvaluator requires a callable Python object")

        from domnir.api.jobs import ActionBounds, parse_action
        from domnir.scenario import calculate_applied_disturbance
        import json
        import mujoco
        import numpy as np

        model = mujoco.MjModel.from_xml_path(str(model_path))
        body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
        bounds = ActionBounds(
            tuple(float(x) for x in model.actuator_ctrlrange[:, 0]),
            tuple(float(x) for x in model.actuator_ctrlrange[:, 1]),
        )
        data = mujoco.MjData(model)
        data.qpos[2] = float(scenario.initial_altitude_m)
        mujoco.mj_forward(model, data)

        steps = contract.physics_steps
        trajectory: list[dict[str, Any]] = [{
            "step_index": 0,
            "sim_time_s": 0.0,
            "position_m": data.qpos[:3].tolist(),
            "velocity_mps": data.qvel[:3].tolist(),
            "orientation_quat_wxyz": data.qpos[3:7].tolist(),
            "altitude_error_m": float(data.qpos[2] - contract.target_altitude_m),
            "action": [0.0, 0.0, 0.0, 0.0],
            "applied_disturbance_n": 0.0,
        }]

        recorded_actions: list[list[float]] = []
        recorded_states: list[list[float]] = [np.concatenate((data.qpos, data.qvel)).tolist()]

        for step_idx in range(steps):
            sim_time = float(data.time)
            observation = {
                "schema_version": "1.0",
                "trial_id": "trusted-harness-run",
                "step_index": step_idx,
                "sim_time_s": sim_time,
                "dt_s": float(model.opt.timestep),
                "position_m": data.qpos[:3].tolist(),
                "velocity_mps": data.qvel[:3].tolist(),
                "orientation_quat_wxyz": data.qpos[3:7].tolist(),
                "body_angular_velocity_rps": data.qvel[3:6].tolist(),
                "target_position_m": [0.0, 0.0, float(contract.target_altitude_m)],
                "target_altitude_m": float(contract.target_altitude_m),
            }

            raw_act = observe_fn(observation)
            resp_bytes = json.dumps(raw_act, allow_nan=False, separators=(",", ":")).encode("utf-8")
            action = parse_action(
                resp_bytes,
                trial_id="trusted-harness-run",
                step_index=step_idx,
                bounds=bounds,
            )

            f_z = calculate_applied_disturbance(scenario, sim_time)
            data.ctrl[:] = action
            data.xfrc_applied[body_id, 2] = f_z
            mujoco.mj_step(model, data)

            recorded_actions.append(list(action))
            state_vec = np.concatenate((data.qpos, data.qvel))
            recorded_states.append(state_vec.tolist())

            trajectory.append({
                "step_index": step_idx + 1,
                "sim_time_s": float(data.time),
                "position_m": data.qpos[:3].tolist(),
                "velocity_mps": data.qvel[:3].tolist(),
                "orientation_quat_wxyz": data.qpos[3:7].tolist(),
                "altitude_error_m": float(data.qpos[2] - contract.target_altitude_m),
                "action": list(action),
                "applied_disturbance_n": float(f_z),
            })

            if not np.isfinite(state_vec).all():
                break

        return ControllerExecutionResult(
            status="SUCCESS",
            backend=ExecutionBackend.TRUSTED_HARNESS,
            trajectory=trajectory,
            actions=recorded_actions,
            states=recorded_states,
        )

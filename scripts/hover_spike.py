"""Run a local, trusted-only Crazyflie model and replay check."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path

import mujoco
import numpy as np


def file_hashes(model_path: Path) -> dict[str, str]:
    files = [model_path, *sorted((model_path.parent / "assets").glob("*.obj"))]
    return {
        str(path.relative_to(model_path.parent)): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in files
    }


def run(model_path: Path, steps: int) -> dict:
    model = mujoco.MjModel.from_xml_path(str(model_path))
    if model.nu != 4 or model.nq != 7 or model.nv != 6:
        raise ValueError("Expected the standalone Crazyflie free-body model")
    if steps <= 0 or steps > 100_000:
        raise ValueError("steps must be between 1 and 100000")

    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
    if body_id < 0:
        raise ValueError("Crazyflie body not found")
    hover_thrust = float(model.body_mass[body_id] * -model.opt.gravity[2])
    if (
        not model.actuator_ctrlrange[0, 0]
        <= hover_thrust
        <= model.actuator_ctrlrange[0, 1]
    ):
        raise ValueError("Hover thrust exceeds the model's thrust range")
    target_z = 0.1
    initial_offset_z = 0.05

    def simulate(
        instance: mujoco.MjModel, recorded_actions: np.ndarray | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        data = mujoco.MjData(instance)
        data.qpos[2] = target_z + initial_offset_z
        trace = np.empty((steps + 1, instance.nq + instance.nv))
        actions = np.empty((steps, instance.nu))
        trace[0] = np.concatenate((data.qpos, data.qvel))
        for index in range(steps):
            if recorded_actions is None:
                thrust = (
                    hover_thrust
                    + 0.15 * (target_z - data.qpos[2])
                    - 0.08 * data.qvel[2]
                )
                actions[index] = [
                    np.clip(thrust, *instance.actuator_ctrlrange[0]),
                    0.0,
                    0.0,
                    0.0,
                ]
            else:
                actions[index] = recorded_actions[index]
            data.ctrl[:] = actions[index]
            mujoco.mj_step(instance, data)
            trace[index + 1] = np.concatenate((data.qpos, data.qvel))
        return trace, actions

    original, actions = simulate(model)
    replay_model = mujoco.MjModel.from_xml_path(str(model_path))
    replay, _ = simulate(replay_model, actions)
    if not np.isfinite(original).all() or not np.isfinite(replay).all():
        raise ValueError("Simulation produced a non-finite state")
    return {
        "status": "local_hover_spike_only",
        "limitations": "Untuned actuator limits; no physical calibration or safety verdict.",
        "mujoco_version": mujoco.__version__,
        "platform": platform.platform(),
        "model_hashes_sha256": file_hashes(model_path),
        "mass_kg": float(model.body_mass[body_id]),
        "inertia_kg_m2": model.body_inertia[body_id].tolist(),
        "gravity_m_s2": model.opt.gravity.tolist(),
        "timestep_s": model.opt.timestep,
        "integrator": int(model.opt.integrator),
        "actuator_ctrlrange": model.actuator_ctrlrange.tolist(),
        "hover_thrust_n": hover_thrust,
        "target_altitude_m": target_z,
        "initial_altitude_offset_m": initial_offset_z,
        "altitude_controller_gains": {"position": 0.15, "velocity": 0.08},
        "final_altitude_error_m": float(original[-1, 2] - target_z),
        "steps": steps,
        "max_position_drift_m": float(
            np.max(np.linalg.norm(original[:, :3] - original[0, :3], axis=1))
        ),
        "replay_max_abs_state_difference": float(np.max(np.abs(original - replay))),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=1000)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.model.resolve(strict=True), args.steps), indent=2, allow_nan=False
        )
    )


if __name__ == "__main__":
    main()

"""Capture and restore MuJoCo's integration state for deterministic replay."""

from __future__ import annotations

import hashlib
import platform
from pathlib import Path
from typing import Any

import mujoco
import numpy as np

INTEGRATION_SIGNATURE = int(mujoco.mjtState.mjSTATE_INTEGRATION)


def model_hashes(model_path: Path) -> dict[str, str]:
    return {
        str(path.relative_to(model_path.parent)): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in [model_path, *sorted((model_path.parent / "assets").glob("*.obj"))]
    }


def capture_integration_state(model: mujoco.MjModel, data: mujoco.MjData) -> np.ndarray:
    state = np.empty(
        mujoco.mj_stateSize(model, INTEGRATION_SIGNATURE), dtype=np.float64
    )
    mujoco.mj_getState(model, data, state, INTEGRATION_SIGNATURE)
    if not np.isfinite(state).all():
        raise ValueError("Integration state contains a non-finite value")
    return state


def restore_integration_state(
    model: mujoco.MjModel, data: mujoco.MjData, state: np.ndarray
) -> None:
    expected = mujoco.mj_stateSize(model, INTEGRATION_SIGNATURE)
    values = np.asarray(state, dtype=np.float64)
    if values.shape != (expected,) or not np.isfinite(values).all():
        raise ValueError("Integration state has an invalid shape or value")
    mujoco.mj_setState(model, data, values, INTEGRATION_SIGNATURE)


def replay_saved_trajectory(
    model_path: Path, result: dict[str, Any], *, tolerance: float
) -> float:
    if (
        result["mujoco_version"] != mujoco.__version__
        or result["platform"] != platform.platform()
    ):
        raise ValueError("Replay environment differs from the recorded environment")
    if result["integration_signature"] != INTEGRATION_SIGNATURE:
        raise ValueError("Unsupported integration state signature")
    expected_hashes = result["model_hashes_sha256"]
    if model_hashes(model_path) != expected_hashes:
        raise ValueError("Model files do not match the recorded hashes")
    model = mujoco.MjModel.from_xml_path(str(model_path))
    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
    if model.nu != 4 or body_id < 0 or not np.all(model.actuator_ctrllimited):
        raise ValueError("Unexpected replay model")
    steps = result["steps"]
    if (
        type(steps) is not int
        or not 1 <= steps <= 1000
        or result["timestep_s"] != model.opt.timestep
    ):
        raise ValueError("Invalid recorded step count or timestep")
    actions = np.asarray(result["actions"], dtype=np.float64)
    recorded = np.asarray(result["integration_states"], dtype=np.float64)
    state_size = mujoco.mj_stateSize(model, INTEGRATION_SIGNATURE)
    if (
        actions.shape != (steps, 4)
        or recorded.shape != (steps + 1, state_size)
        or not np.isfinite(actions).all()
        or not np.isfinite(recorded).all()
        or np.any(actions < model.actuator_ctrlrange[:, 0])
        or np.any(actions > model.actuator_ctrlrange[:, 1])
    ):
        raise ValueError("Invalid recorded action or integration state")
    disturbance = result["vertical_disturbance_n"]
    if (
        not isinstance(disturbance, (float, int))
        or not np.isfinite(disturbance)
        or not -0.05 <= disturbance <= 0.05
    ):
        raise ValueError("Invalid recorded disturbance")
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Invalid replay tolerance")
    data = mujoco.MjData(model)
    restore_integration_state(model, data, recorded[0])
    maximum = float(
        np.max(np.abs(capture_integration_state(model, data) - recorded[0]))
    )
    for index, action in enumerate(actions):
        data.ctrl[:] = action
        data.xfrc_applied[body_id, 2] = disturbance
        mujoco.mj_step(model, data)
        maximum = max(
            maximum,
            float(
                np.max(
                    np.abs(capture_integration_state(model, data) - recorded[index + 1])
                )
            ),
        )
    if model_hashes(model_path) != expected_hashes:
        raise ValueError("Model files changed during replay")
    if maximum > tolerance:
        raise ValueError("Saved trajectory replay diverged")
    return maximum

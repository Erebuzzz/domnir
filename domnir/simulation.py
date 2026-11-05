"""A trusted, minimal MuJoCo action and replay kernel.

The supplied model's actuator limits remain research assumptions until calibrated.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mujoco
import numpy as np

from .protocol import ActionBounds, parse_action


@dataclass(frozen=True)
class SimulationResult:
    actions: np.ndarray
    states: np.ndarray
    replay_max_abs_difference: float


def run_trial(model_path: Path, trial_id: str, frames: list[bytes]) -> SimulationResult:
    if not trial_id or not 1 <= len(frames) <= 100_000:
        raise ValueError("A trial ID and a bounded, nonempty frame list are required")
    model = mujoco.MjModel.from_xml_path(str(model_path))
    if model.nu != 4 or model.nq != 7 or model.nv != 6:
        raise ValueError("Expected a four-actuator Crazyflie free-body model")
    if not np.all(model.actuator_ctrllimited):
        raise ValueError("Every actuator must have explicit limits")
    bounds = ActionBounds(
        tuple(float(x) for x in model.actuator_ctrlrange[:, 0]),
        tuple(float(x) for x in model.actuator_ctrlrange[:, 1]),
    )
    actions = np.array(
        [
            parse_action(frame, trial_id=trial_id, step_index=index, bounds=bounds)
            for index, frame in enumerate(frames)
        ],
        dtype=np.float64,
    )

    def simulate(instance: mujoco.MjModel) -> np.ndarray:
        data = mujoco.MjData(instance)
        states = np.empty((len(actions) + 1, instance.nq + instance.nv))
        states[0] = np.concatenate((data.qpos, data.qvel))
        for index, action in enumerate(actions):
            data.ctrl[:] = action
            mujoco.mj_step(instance, data)
            states[index + 1] = np.concatenate((data.qpos, data.qvel))
        if not np.isfinite(states).all():
            raise ValueError("Simulator produced a non-finite state")
        return states

    states = simulate(model)
    replay = simulate(mujoco.MjModel.from_xml_path(str(model_path)))
    return SimulationResult(actions, states, float(np.max(np.abs(states - replay))))

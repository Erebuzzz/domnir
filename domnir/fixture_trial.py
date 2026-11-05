"""Run a fixed guest fixture against the trusted MuJoCo plant.

This feasibility path intentionally accepts no controller source or executable path.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import selectors
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import mujoco
import numpy as np

from .protocol import MAX_FRAME_BYTES, ActionBounds, parse_action
from .replay import (
    INTEGRATION_SIGNATURE,
    capture_integration_state,
    model_hashes,
    restore_integration_state,
)
from .sandbox import IMAGE, RUNTIME_VERSION, SandboxLease

FIXTURE = """import json, sys
for line in sys.stdin.buffer:
    observation = json.loads(line)
    z = observation['position_m'][2]
    vz = observation['velocity_mps'][2]
    thrust = max(0.0, min(0.35, 0.26487 + 0.15 * (0.1 - z) - 0.08 * vz))
    action = {'schema_version':'1.0', 'trial_id':observation['trial_id'],
              'step_index':observation['step_index'], 'thrust':thrust,
              'moment_x':0.0, 'moment_y':0.0, 'moment_z':0.0}
    print(json.dumps(action, allow_nan=False), flush=True)
"""

GUEST_RUNNER = """import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('controller', '/tmp/domnir-controller.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for line in sys.stdin.buffer:
    observation = json.loads(line)
    action = module.observe(observation)
    print(json.dumps(action, allow_nan=False, separators=(',', ':')), flush=True)
"""


class ChannelError(RuntimeError):
    """The guest controller stream failed or exceeded its limits."""


@dataclass(frozen=True)
class FixtureTrialResult:
    steps: int
    final_altitude_error_m: float
    minimum_altitude_m: float
    replay_max_abs_difference: float
    max_roundtrip_ms: float
    trial_id: str
    initial_altitude_m: float
    vertical_disturbance_n: float
    timestep_s: float
    mujoco_version: str
    platform: str
    runtime_version: str
    guest_image: str
    fixture_sha256: str | None
    controller_sha256: str
    guest_runner_sha256: str | None
    source_kind: str
    model_hashes_sha256: dict[str, str]
    actions: list[list[float]]
    states: list[list[float]]
    replay_states: list[list[float]]
    integration_signature: int
    integration_states: list[list[float]]
    replay_integration_states: list[list[float]]


class _GuestStream:
    def __init__(
        self,
        lease: SandboxLease,
        *,
        controller: bool = False,
        fixed_program: str | None = None,
    ) -> None:
        if not lease.active:
            raise ChannelError("A verified active sandbox is required")
        self.process = subprocess.Popen(
            [
                lease.executable,
                "exec",
                "--stream",
                lease.name,
                "--",
                "python",
                "-u",
                "-c",
                fixed_program
                if fixed_program is not None
                else GUEST_RUNNER
                if controller
                else FIXTURE,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        if self.process.stdin is None or self.process.stdout is None:
            self.process.kill()
            self.process.wait()
            raise ChannelError("Could not establish guest pipes")
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout
        os.set_blocking(self.stdin.fileno(), False)
        os.set_blocking(self.stdout.fileno(), False)
        self.selector = selectors.DefaultSelector()

    def exchange(self, observation: dict, timeout_s: float) -> bytes:
        request = (
            json.dumps(observation, allow_nan=False, separators=(",", ":")).encode()
            + b"\n"
        )
        if len(request) > MAX_FRAME_BYTES:
            raise ChannelError("Observation exceeds the frame limit")
        deadline = time.monotonic() + timeout_s
        sent = 0
        received = bytearray()
        self.selector.register(self.stdin, selectors.EVENT_WRITE)
        try:
            while sent < len(request):
                self._wait(deadline)
                try:
                    sent += os.write(self.stdin.fileno(), request[sent:])
                except BlockingIOError:
                    continue
                except OSError as error:
                    raise ChannelError("Guest input closed") from error
            self.selector.unregister(self.stdin)
            self.selector.register(self.stdout, selectors.EVENT_READ)
            while b"\n" not in received:
                self._wait(deadline)
                try:
                    chunk = os.read(self.stdout.fileno(), MAX_FRAME_BYTES + 1)
                except BlockingIOError:
                    continue
                if not chunk:
                    raise ChannelError("Guest output closed")
                received.extend(chunk)
                if len(received) > MAX_FRAME_BYTES:
                    raise ChannelError("Guest response exceeds the frame limit")
            line, _, remainder = received.partition(b"\n")
            if remainder:
                raise ChannelError("Unexpected data after guest response")
            return bytes(line)
        finally:
            for fileobj in (self.stdin, self.stdout):
                try:
                    self.selector.unregister(fileobj)
                except KeyError:
                    pass

    def _wait(self, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self.selector.select(remaining):
            raise ChannelError("Guest response deadline exceeded")

    def close(self) -> None:
        self.selector.close()
        self.stdin.close()
        self.stdout.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)


def run_fixture_trial(
    model_path: Path,
    lease: SandboxLease,
    *,
    trial_id: str,
    steps: int = 200,
    timeout_s: float = 1.0,
    initial_altitude_m: float = 0.15,
    vertical_disturbance_n: float = 0.0,
    _controller_source: bytes | None = None,
) -> FixtureTrialResult:
    if (
        not trial_id
        or not 1 <= steps <= 1000
        or not math.isfinite(timeout_s)
        or not 0 < timeout_s <= 5
    ):
        raise ValueError("Invalid trial ID, step count, or deadline")
    if (
        not math.isfinite(initial_altitude_m)
        or not 0.05 <= initial_altitude_m <= 0.5
        or not math.isfinite(vertical_disturbance_n)
        or not -0.05 <= vertical_disturbance_n <= 0.05
    ):
        raise ValueError("Scenario is outside the declared feasibility envelope")
    initial_hashes = model_hashes(model_path)
    model = mujoco.MjModel.from_xml_path(str(model_path))
    if (
        model.nu != 4
        or model.nq != 7
        or model.nv != 6
        or not np.all(model.actuator_ctrllimited)
    ):
        raise ValueError("Expected the four-actuator Crazyflie free-body model")
    bounds = ActionBounds(
        tuple(float(x) for x in model.actuator_ctrlrange[:, 0]),
        tuple(float(x) for x in model.actuator_ctrlrange[:, 1]),
    )
    data = mujoco.MjData(model)
    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
    if body_id < 0:
        raise ValueError("Crazyflie body not found")
    data.qpos[2] = initial_altitude_m
    states = np.empty((steps + 1, model.nq + model.nv))
    actions = np.empty((steps, model.nu))
    states[0] = np.concatenate((data.qpos, data.qvel))
    initial_integration_state = capture_integration_state(model, data)
    integration_states = np.empty((steps + 1, len(initial_integration_state)))
    integration_states[0] = initial_integration_state
    durations: list[float] = []
    controller_digest = (
        lease.install_controller(_controller_source)
        if _controller_source is not None
        else hashlib.sha256(FIXTURE.encode("utf-8")).hexdigest()
    )
    stream = _GuestStream(lease, controller=_controller_source is not None)
    try:
        for index in range(steps):
            observation = {
                "schema_version": "1.0",
                "trial_id": trial_id,
                "step_index": index,
                "sim_time_s": float(data.time),
                "dt_s": float(model.opt.timestep),
                "position_m": data.qpos[:3].tolist(),
                "velocity_mps": data.qvel[:3].tolist(),
                "orientation_quat_wxyz": data.qpos[3:7].tolist(),
                "body_angular_velocity_rps": data.qvel[3:6].tolist(),
                "target_position_m": [0.0, 0.0, 0.1],
            }
            started = time.monotonic()
            response = stream.exchange(observation, timeout_s)
            durations.append(time.monotonic() - started)
            action = parse_action(
                response, trial_id=trial_id, step_index=index, bounds=bounds
            )
            actions[index] = action
            data.ctrl[:] = action
            data.xfrc_applied[body_id, 2] = vertical_disturbance_n
            mujoco.mj_step(model, data)
            states[index + 1] = np.concatenate((data.qpos, data.qvel))
            integration_states[index + 1] = capture_integration_state(model, data)
            if not np.isfinite(states[index + 1]).all():
                raise ValueError("Simulator produced a non-finite state")
    finally:
        stream.close()

    if model_hashes(model_path) != initial_hashes:
        raise ValueError("Model files changed during the trial")
    replay_model = mujoco.MjModel.from_xml_path(str(model_path))
    replay_data = mujoco.MjData(replay_model)
    replay_body_id = mujoco.mj_name2id(replay_model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
    if replay_body_id < 0:
        raise ValueError("Crazyflie body missing from replay model")
    restore_integration_state(replay_model, replay_data, initial_integration_state)
    replay_states = np.empty_like(states)
    replay_states[0] = np.concatenate((replay_data.qpos, replay_data.qvel))
    replay_integration_states = np.empty_like(integration_states)
    replay_integration_states[0] = capture_integration_state(replay_model, replay_data)
    for index, action in enumerate(actions):
        replay_data.ctrl[:] = action
        replay_data.xfrc_applied[replay_body_id, 2] = vertical_disturbance_n
        mujoco.mj_step(replay_model, replay_data)
        replay_states[index + 1] = np.concatenate((replay_data.qpos, replay_data.qvel))
        replay_integration_states[index + 1] = capture_integration_state(
            replay_model, replay_data
        )
    if not np.isfinite(replay_states).all():
        raise ValueError("Replay produced a non-finite state")
    if model_hashes(model_path) != initial_hashes:
        raise ValueError("Model files changed during replay")
    return FixtureTrialResult(
        steps,
        float(states[-1, 2] - 0.1),
        float(np.min(states[:, 2])),
        max(
            float(np.max(np.abs(states - replay_states))),
            float(np.max(np.abs(integration_states - replay_integration_states))),
        ),
        max(durations) * 1000,
        trial_id,
        initial_altitude_m,
        vertical_disturbance_n,
        float(model.opt.timestep),
        mujoco.__version__,
        platform.platform(),
        RUNTIME_VERSION,
        IMAGE,
        hashlib.sha256(FIXTURE.encode("utf-8")).hexdigest()
        if _controller_source is None
        else None,
        controller_digest,
        hashlib.sha256(GUEST_RUNNER.encode("utf-8")).hexdigest()
        if _controller_source is not None
        else None,
        "fixed_fixture" if _controller_source is None else "guest_controller",
        initial_hashes,
        actions.tolist(),
        states.tolist(),
        replay_states.tolist(),
        INTEGRATION_SIGNATURE,
        integration_states.tolist(),
        replay_integration_states.tolist(),
    )


def run_controller_trial(
    model_path: Path, lease: SandboxLease, source: bytes, **kwargs
) -> FixtureTrialResult:
    """Run source only within an existing verified guest, using the feasibility plant."""
    return run_fixture_trial(model_path, lease, _controller_source=source, **kwargs)

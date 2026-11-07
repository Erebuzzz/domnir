"""Experiment orchestration, state machine transitions, and job management."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mujoco
import numpy as np

from domnir.api.models import (
    ArtifactsResponse,
    ExperimentDetailResponse,
    ExperimentState,
    ExperimentSummary,
    RunExperimentRequest,
    StateTransitionRecord,
)
from domnir.court_record import build_court_record, chain_events
from domnir.inference.vultr import DEFAULT_MODEL, VultrInferenceClient, resolve_model_id
from domnir.protocol import ActionBounds, parse_action
from domnir.replay import (
    INTEGRATION_SIGNATURE,
    capture_integration_state,
    restore_integration_state,
)
from domnir.sandbox import SandboxLease
from domnir.scenario import ScenarioParameter, calculate_applied_disturbance
from domnir.spec import FlightSpec, GeneratedController

MAX_QUEUED_JOBS = 20
MAX_CONCURRENT_JOBS = 2

ALLOWED_TRANSITIONS: dict[ExperimentState, set[ExperimentState]] = {
    ExperimentState.CREATED: {
        ExperimentState.SPEC_APPROVED,
        ExperimentState.FAILED,
    },
    ExperimentState.SPEC_APPROVED: {
        ExperimentState.CONTROLLER_VALIDATED,
        ExperimentState.FAILED,
    },
    ExperimentState.CONTROLLER_VALIDATED: {
        ExperimentState.QUEUED,
        ExperimentState.FAILED,
    },
    ExperimentState.QUEUED: {
        ExperimentState.RUNNING,
        ExperimentState.FAILED,
    },
    ExperimentState.RUNNING: {
        ExperimentState.COMPLETED,
        ExperimentState.FAILED,
        ExperimentState.INCONCLUSIVE,
    },
    ExperimentState.COMPLETED: set(),
    ExperimentState.FAILED: set(),
    ExperimentState.INCONCLUSIVE: set(),
}


def get_default_model_path() -> Path:
    env_path = os.environ.get("DOMNIR_SPIKE_MODEL")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
    candidates = [
        Path.cwd() / ".cache" / "mujoco_menagerie" / "bitcraze_crazyflie_2" / "cf2.xml",
        Path(__file__).resolve().parents[2] / ".cache" / "mujoco_menagerie" / "bitcraze_crazyflie_2" / "cf2.xml",
        Path(__file__).resolve().parents[1] / ".cache" / "mujoco_menagerie" / "bitcraze_crazyflie_2" / "cf2.xml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def file_hashes(model_path: Path) -> dict[str, str]:
    files = [model_path]
    assets_dir = model_path.parent / "assets"
    if assets_dir.is_dir():
        files.extend(sorted(assets_dir.glob("*.obj")))
    return {
        str(path.relative_to(model_path.parent)): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in files
    }


def is_microvm_available() -> bool:
    msb_bin = os.environ.get("DOMNIR_MSB") or shutil.which("msb")
    kvm_accessible = os.path.exists("/dev/kvm") and os.access("/dev/kvm", os.R_OK | os.W_OK)
    return bool(msb_bin and kvm_accessible)


class StateTransitionError(ValueError):
    """Raised when an illegal state machine transition is attempted."""


class _IsolatedSubprocessGuestStream:
    def __init__(self, source_code: str, timeout_seconds: float = 2.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.temp_dir = tempfile.TemporaryDirectory(prefix="domnir-guest-")
        controller_path = Path(self.temp_dir.name) / "controller.py"
        controller_path.write_text(source_code, encoding="utf-8")

        runner_code = (
            "import importlib.util, json, sys\n"
            "try:\n"
            "    spec = importlib.util.spec_from_file_location('controller', sys.argv[1])\n"
            "    mod = importlib.util.module_from_spec(spec)\n"
            "    spec.loader.exec_module(mod)\n"
            "    obs_fn = getattr(mod, 'observe', None)\n"
            "    if obs_fn is None:\n"
            "        sys.stderr.write('observe function missing\\n')\n"
            "        sys.exit(1)\n"
            "except Exception as e:\n"
            "    sys.stderr.write(f'Module load error: {e}\\n')\n"
            "    sys.exit(1)\n"
            "for line in sys.stdin:\n"
            "    line = line.strip()\n"
            "    if not line:\n"
            "        continue\n"
            "    try:\n"
            "        obs = json.loads(line)\n"
            "        act = obs_fn(obs)\n"
            "        sys.stdout.write(json.dumps(act, allow_nan=False, separators=(',', ':')) + '\\n')\n"
            "        sys.stdout.flush()\n"
            "    except Exception as e:\n"
            "        sys.stderr.write(f'Observe error: {e}\\n')\n"
            "        sys.exit(2)\n"
        )

        clean_env = {
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PATH": os.environ.get("PATH", ""),
            "PATHEXT": os.environ.get("PATHEXT", ""),
            "PYTHONPATH": "",
        }

        self.process = subprocess.Popen(
            [sys.executable, "-u", "-c", runner_code, str(controller_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=clean_env,
            bufsize=1,
        )
        self.closed = False

    def exchange(self, observation: dict[str, Any]) -> str:
        if self.process.poll() is not None:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"Guest process exited with code {self.process.returncode}: {stderr.strip()}")

        payload = json.dumps(observation, allow_nan=False, separators=(",", ":"))
        if len(payload.encode("utf-8")) > 4096:
            raise ValueError("Observation payload exceeds max frame bytes")

        try:
            self.process.stdin.write(payload + "\n")
            self.process.stdin.flush()
        except OSError as e:
            raise RuntimeError(f"Failed to write to guest: {e}") from e

        res: list[str | None] = [None]
        err: list[Exception | None] = [None]

        def reader() -> None:
            try:
                res[0] = self.process.stdout.readline()
            except Exception as read_err:
                err[0] = read_err

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(self.timeout_seconds)
        if t.is_alive():
            self.close()
            raise TimeoutError(f"Guest failed to respond within {self.timeout_seconds}s")
        if err[0]:
            raise RuntimeError(f"Error reading from guest: {err[0]}")

        line = res[0]
        if not line:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"Guest process closed unexpectedly: {stderr.strip()}")
        return line.strip()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            if self.process.stdin:
                try:
                    self.process.stdin.close()
                except Exception:
                    pass
            if self.process.stdout:
                try:
                    self.process.stdout.close()
                except Exception:
                    pass
            if self.process.stderr:
                try:
                    self.process.stderr.close()
                except Exception:
                    pass
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=1.0)
        finally:
            self.temp_dir.cleanup()


class _MicroVMGuestStream:
    def __init__(self, lease: SandboxLease, timeout_seconds: float = 2.0) -> None:
        from domnir.fixture_trial import _GuestStream
        self.lease = lease
        self.timeout_seconds = timeout_seconds
        self.stream = _GuestStream(lease, controller=True)

    def exchange(self, observation: dict[str, Any]) -> str:
        resp_bytes = self.stream.exchange(observation, timeout_s=self.timeout_seconds)
        return resp_bytes.decode("utf-8")

    def close(self) -> None:
        self.stream.close()


class ExperimentJob:
    def __init__(
        self,
        experiment_id: str,
        spec: FlightSpec,
        *,
        controller: GeneratedController | None = None,
        controller_source: str | None = None,
        model_id: str | None = None,
        reasoning_effort: str | None = None,
        steps: int | None = None,
        initial_altitude_m: float = 0.15,
        vertical_disturbance_n: float = 0.0,
        pulse_start_s: float = 0.0,
        pulse_duration_s: float = 0.0,
        seed: int = 42,
    ) -> None:
        self.id = experiment_id
        self.spec = spec
        self.controller = controller
        self.controller_source = controller_source
        self.model_id = model_id or (controller.model_id if controller else DEFAULT_MODEL)
        self.reasoning_effort = reasoning_effort
        self.steps = steps or spec.step_budget
        self.initial_altitude_m = initial_altitude_m
        self.vertical_disturbance_n = vertical_disturbance_n
        self.pulse_start_s = pulse_start_s
        self.pulse_duration_s = pulse_duration_s
        self.scenario = ScenarioParameter(
            initial_altitude_m=initial_altitude_m,
            disturbance_force_z=vertical_disturbance_n,
            pulse_start_s=pulse_start_s,
            pulse_duration_s=pulse_duration_s,
        )
        self.seed = seed

        now = datetime.now(timezone.utc).isoformat()
        self.created_at = now
        self.updated_at = now
        self.state = ExperimentState.CREATED
        self.state_history: list[StateTransitionRecord] = [
            StateTransitionRecord(
                from_state=None,
                to_state=ExperimentState.CREATED,
                timestamp=now,
                reason="Job initialized",
            )
        ]

        self.verdict: str | None = None
        self.execution_backend: str = "trusted_simulator"
        self.steps_completed: int = 0
        self.final_altitude_m: float | None = None
        self.minimum_altitude_m: float | None = None
        self.maximum_altitude_m: float | None = None
        self.altitude_error_m: float | None = None
        self.replay_max_abs_difference: float | None = None
        self.replay_matched: bool | None = None
        self.error_message: str | None = None
        self.cleanup_succeeded: bool = True

        self.trajectory: list[dict[str, Any]] = []
        self.event_log: list[dict[str, Any]] = []
        self.court_record: dict[str, Any] | None = None

        self._active_stream: Any = None
        self._active_lease: Any = None

    def transition_to(self, target_state: ExperimentState, reason: str | None = None) -> None:
        allowed = ALLOWED_TRANSITIONS.get(self.state, set())
        if target_state not in allowed:
            raise StateTransitionError(
                f"Illegal state transition from {self.state} to {target_state}"
            )
        now = datetime.now(timezone.utc).isoformat()
        record = StateTransitionRecord(
            from_state=self.state,
            to_state=target_state,
            timestamp=now,
            reason=reason,
        )
        self.state = target_state
        self.updated_at = now
        self.state_history.append(record)
        self.event_log.append({
            "event_type": "state_transition",
            "from_state": record.from_state,
            "to_state": target_state,
            "timestamp": now,
            "reason": reason,
        })

    def to_summary(self) -> ExperimentSummary:
        return ExperimentSummary(
            id=self.id,
            state=self.state,
            created_at=self.created_at,
            updated_at=self.updated_at,
            spec=self.spec,
            controller_sha256=self.controller.source_sha256 if self.controller else None,
            model_id=self.model_id,
            verdict=self.verdict,
            execution_backend=self.execution_backend,
            steps_completed=self.steps_completed,
            final_altitude_m=self.final_altitude_m,
            minimum_altitude_m=self.minimum_altitude_m,
            maximum_altitude_m=self.maximum_altitude_m,
            altitude_error_m=self.altitude_error_m,
            replay_max_abs_difference=self.replay_max_abs_difference,
            replay_matched=self.replay_matched,
            error_message=self.error_message,
            cleanup_succeeded=self.cleanup_succeeded,
        )

    def to_detail(self) -> ExperimentDetailResponse:
        artifacts: list[str] = []
        if self.court_record is not None:
            artifacts.append("court_record")
        if self.trajectory:
            artifacts.append("trajectory")
        if self.event_log:
            artifacts.append("event_log")

        summary = self.to_summary()
        return ExperimentDetailResponse(
            **summary.model_dump(),
            state_history=self.state_history,
            telemetry_sample_count=len(self.trajectory),
            artifacts_available=artifacts,
        )

    def to_artifacts(self) -> ArtifactsResponse:
        return ArtifactsResponse(
            experiment_id=self.id,
            state=self.state,
            court_record=self.court_record,
            trajectory=self.trajectory,
            event_log=self.event_log,
        )


class JobOrchestrator:
    def __init__(
        self,
        *,
        max_concurrency: int = MAX_CONCURRENT_JOBS,
        max_queue_size: int = MAX_QUEUED_JOBS,
        model_path: Path | None = None,
        inference_client: VultrInferenceClient | None = None,
    ) -> None:
        self.max_concurrency = max_concurrency
        self.max_queue_size = max_queue_size
        self.model_path = model_path or get_default_model_path()
        self.inference_client = inference_client or VultrInferenceClient()
        self._jobs: dict[str, ExperimentJob] = {}
        self._semaphore = threading.Semaphore(max_concurrency)
        self._lock = threading.Lock()

    def get_job(self, job_id: str) -> ExperimentJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[ExperimentJob]:
        with self._lock:
            return list(self._jobs.values())

    def create_job(self, request: RunExperimentRequest) -> ExperimentJob:
        with self._lock:
            active_count = sum(
                1 for j in self._jobs.values()
                if j.state not in (ExperimentState.COMPLETED, ExperimentState.FAILED, ExperimentState.INCONCLUSIVE)
            )
            if active_count >= self.max_queue_size:
                raise RuntimeError(
                    f"Job queue limit reached ({self.max_queue_size} active/queued jobs)"
                )

            experiment_id = str(uuid.uuid4())
            resolved_model = resolve_model_id(request.model) if request.model else None
            job = ExperimentJob(
                experiment_id=experiment_id,
                spec=request.spec,
                controller=request.controller,
                controller_source=request.controller_source,
                model_id=resolved_model,
                reasoning_effort=request.reasoning_effort,
                steps=request.steps,
                initial_altitude_m=request.initial_altitude_m,
                vertical_disturbance_n=request.vertical_disturbance_n,
                pulse_start_s=request.pulse_start_s,
                pulse_duration_s=request.pulse_duration_s,
                seed=request.seed,
            )
            self._jobs[experiment_id] = job
            return job

    def execute_job(self, job: ExperimentJob) -> ExperimentJob:
        try:
            # 1. Spec Approval
            job.transition_to(ExperimentState.SPEC_APPROVED, reason="Specification verified")

            # 2. Controller Validation or Generation
            if job.controller is None:
                if job.controller_source:
                    job.controller = GeneratedController.from_source(
                        job.controller_source,
                        model_id=job.model_id or "user_supplied",
                    )
                else:
                    target_model = resolve_model_id(job.model_id or DEFAULT_MODEL)
                    job.controller = self.inference_client.generate_controller(
                        job.spec,
                        model=target_model,
                        reasoning_effort=job.reasoning_effort or "minimal",
                    )
            job.transition_to(ExperimentState.CONTROLLER_VALIDATED, reason="Controller code validated")

            # 3. Queued
            job.transition_to(ExperimentState.QUEUED, reason="Enqueued for worker slot")

            acquired = self._semaphore.acquire(timeout=60.0)
            if not acquired:
                raise RuntimeError("Worker acquisition timed out waiting for concurrency slot")

            try:
                # 4. Running
                job.transition_to(ExperimentState.RUNNING, reason="Execution slot acquired")
                self._run_simulation(job)
            finally:
                self._semaphore.release()

        except Exception as error:
            if job.state not in (ExperimentState.FAILED, ExperimentState.INCONCLUSIVE):
                try:
                    job.transition_to(ExperimentState.FAILED, reason=str(error))
                except StateTransitionError:
                    job.state = ExperimentState.FAILED
            job.error_message = str(error)
            if job.verdict is None:
                job.verdict = "FAILED"
        finally:
            self._run_terminal_cleanup(job)

        return job

    def _run_terminal_cleanup(self, job: ExperimentJob) -> None:
        cleanup_ok = True
        if job._active_stream is not None:
            try:
                job._active_stream.close()
            except Exception:
                cleanup_ok = False
            finally:
                job._active_stream = None

        if job._active_lease is not None:
            try:
                job._active_lease.remove()
                if not getattr(job._active_lease, "cleanup_succeeded", True):
                    cleanup_ok = False
            except Exception:
                cleanup_ok = False
            finally:
                job._active_lease = None

        job.cleanup_succeeded = cleanup_ok
        job.event_log.append({
            "event_type": "cleanup_completed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": {
                "cleanup_succeeded": job.cleanup_succeeded,
                "terminal_state": job.state,
            },
        })
        chained, head_sha = chain_events(job.event_log)
        job.event_log = chained
        if job.court_record is not None:
            job.court_record["cleanup_succeeded"] = cleanup_ok
            if "verdicts" in job.court_record:
                job.court_record["verdicts"]["cleanup_status"] = (
                    "SUCCEEDED" if cleanup_ok else "FAILED"
                )
            if "event_log" in job.court_record:
                job.court_record["event_log"]["events"] = chained
                job.court_record["event_log"]["event_count"] = len(chained)
                job.court_record["event_log"]["head_sha256"] = head_sha
                job.court_record["event_log"]["chain_integrity"] = "VERIFIED"

    def _run_simulation(self, job: ExperimentJob) -> None:
        if not self.model_path.is_file():
            raise FileNotFoundError(f"MuJoCo model not found at {self.model_path}")

        initial_hashes = file_hashes(self.model_path)
        model = mujoco.MjModel.from_xml_path(str(self.model_path))
        if model.nu != 4 or model.nq != 7 or model.nv != 6:
            raise ValueError("Expected four-actuator Crazyflie free-body model")

        body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
        if body_id < 0:
            raise ValueError("Crazyflie body 'cf2' not found in model")

        bounds = ActionBounds(
            tuple(float(x) for x in model.actuator_ctrlrange[:, 0]),
            tuple(float(x) for x in model.actuator_ctrlrange[:, 1]),
        )

        data = mujoco.MjData(model)
        data.qpos[2] = job.initial_altitude_m

        steps = job.steps
        states = np.empty((steps + 1, model.nq + model.nv))
        actions = np.empty((steps, model.nu))
        states[0] = np.concatenate((data.qpos, data.qvel))

        initial_integration_state = capture_integration_state(model, data)
        integration_states = np.empty((steps + 1, len(initial_integration_state)))
        integration_states[0] = initial_integration_state

        trajectory_records: list[dict[str, Any]] = [{
            "step_index": 0,
            "sim_time_s": 0.0,
            "position_m": data.qpos[:3].tolist(),
            "velocity_mps": data.qvel[:3].tolist(),
            "orientation_quat_wxyz": data.qpos[3:7].tolist(),
            "altitude_error_m": float(data.qpos[2] - job.spec.target_altitude_m),
            "action": [0.0, 0.0, 0.0, 0.0],
            "applied_disturbance_n": float(calculate_applied_disturbance(job.scenario, 0.0)),
        }]

        is_prod = os.environ.get("DOMNIR_ENV", os.environ.get("ENV", "")).lower() in {"production", "prod", "live"}

        if is_microvm_available() and job.controller:
            msb_path = Path(os.environ.get("DOMNIR_MSB") or shutil.which("msb"))
            lease = SandboxLease(msb_path, duration_seconds=120)
            lease.__enter__()
            job._active_lease = lease
            lease.install_controller(job.controller.source_code.encode("utf-8"))
            stream: Any = _MicroVMGuestStream(lease)
            job._active_stream = stream
            job.execution_backend = "microvm"
        elif not is_prod and os.environ.get("DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK") == "1":
            if not job.controller:
                raise ValueError("Controller must be validated before simulation")
            stream = _IsolatedSubprocessGuestStream(job.controller.source_code)
            job._active_stream = stream
            job.execution_backend = "subprocess_dev_unisolated"
        else:
            if not job.controller:
                raise ValueError("Controller must be validated before simulation")
            if is_prod and os.environ.get("DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK") == "1":
                raise RuntimeError(
                    "CRITICAL SECURITY VIOLATION: Subprocess execution fallback is strictly prohibited in production mode. Untrusted controllers must run inside verified microVM hardware isolation (/dev/kvm)."
                )
            raise RuntimeError(
                "BLOCKED: ISOLATION_UNAVAILABLE: MicroVM hardware acceleration (/dev/kvm) is required to execute untrusted controller code. Host execution fallback is strictly prohibited in production."
            )

        try:
            for step_idx in range(steps):
                observation = {
                    "schema_version": "1.0",
                    "trial_id": job.id,
                    "step_index": step_idx,
                    "sim_time_s": float(data.time),
                    "dt_s": float(model.opt.timestep),
                    "position_m": data.qpos[:3].tolist(),
                    "velocity_mps": data.qvel[:3].tolist(),
                    "orientation_quat_wxyz": data.qpos[3:7].tolist(),
                    "body_angular_velocity_rps": data.qvel[3:6].tolist(),
                    "target_position_m": [0.0, 0.0, float(job.spec.target_altitude_m)],
                    "target_altitude_m": float(job.spec.target_altitude_m),
                }

                response_str = stream.exchange(observation)
                action = parse_action(
                    response_str.encode("utf-8"),
                    trial_id=job.id,
                    step_index=step_idx,
                    bounds=bounds,
                )

                actions[step_idx] = action
                data.ctrl[:] = action
                f_z = calculate_applied_disturbance(job.scenario, float(data.time))
                data.xfrc_applied[body_id, 2] = f_z
                mujoco.mj_step(model, data)

                states[step_idx + 1] = np.concatenate((data.qpos, data.qvel))
                integration_states[step_idx + 1] = capture_integration_state(model, data)

                trajectory_records.append({
                    "step_index": step_idx + 1,
                    "sim_time_s": float(data.time),
                    "position_m": data.qpos[:3].tolist(),
                    "velocity_mps": data.qvel[:3].tolist(),
                    "orientation_quat_wxyz": data.qpos[3:7].tolist(),
                    "altitude_error_m": float(data.qpos[2] - job.spec.target_altitude_m),
                    "action": list(action),
                    "applied_disturbance_n": float(f_z),
                })

                if not np.isfinite(states[step_idx + 1]).all():
                    raise ValueError("Simulator generated non-finite physical state")
        finally:
            stream.close()
            job._active_stream = None

        job.trajectory = trajectory_records
        job.steps_completed = steps

        if file_hashes(self.model_path) != initial_hashes:
            raise ValueError("Model files changed during simulation")

        replay_model = mujoco.MjModel.from_xml_path(str(self.model_path))
        replay_data = mujoco.MjData(replay_model)
        replay_body_id = mujoco.mj_name2id(replay_model, mujoco.mjtObj.mjOBJ_BODY, "cf2")

        restore_integration_state(replay_model, replay_data, initial_integration_state)
        replay_states = np.empty_like(states)
        replay_states[0] = np.concatenate((replay_data.qpos, replay_data.qvel))
        replay_integration_states = np.empty_like(integration_states)
        replay_integration_states[0] = capture_integration_state(replay_model, replay_data)

        for step_idx, action in enumerate(actions):
            replay_data.ctrl[:] = action
            replay_f_z = calculate_applied_disturbance(job.scenario, float(replay_data.time))
            replay_data.xfrc_applied[replay_body_id, 2] = replay_f_z
            mujoco.mj_step(replay_model, replay_data)
            replay_states[step_idx + 1] = np.concatenate((replay_data.qpos, replay_data.qvel))
            replay_integration_states[step_idx + 1] = capture_integration_state(replay_model, replay_data)

        if not np.isfinite(replay_states).all():
            raise ValueError("Replay produced a non-finite state")

        if file_hashes(self.model_path) != initial_hashes:
            raise ValueError("Model files changed during replay")

        replay_diff = max(
            float(np.max(np.abs(states - replay_states))),
            float(np.max(np.abs(integration_states - replay_integration_states))),
        )
        job.replay_max_abs_difference = replay_diff
        job.replay_matched = bool(replay_diff <= 1e-12)

        all_altitudes = [frame["position_m"][2] for frame in trajectory_records]
        job.final_altitude_m = float(trajectory_records[-1]["position_m"][2])
        job.minimum_altitude_m = float(min(all_altitudes))
        job.maximum_altitude_m = float(max(all_altitudes))
        job.altitude_error_m = float(abs(job.final_altitude_m - job.spec.target_altitude_m))

        if not job.replay_matched:
            job.verdict = "INVALID"
            verdict_reason = f"Replay divergence {replay_diff:.2e} exceeded tolerance 1e-12"
            target_state = ExperimentState.INCONCLUSIVE
        elif job.minimum_altitude_m < job.spec.min_allowed_altitude_m:
            job.verdict = "FALSIFIED"
            verdict_reason = f"Minimum altitude {job.minimum_altitude_m:.4f}m breached floor {job.spec.min_allowed_altitude_m}m"
            target_state = ExperimentState.COMPLETED
        elif job.maximum_altitude_m > job.spec.max_allowed_altitude_m:
            job.verdict = "FALSIFIED"
            verdict_reason = f"Maximum altitude {job.maximum_altitude_m:.4f}m breached ceiling {job.spec.max_allowed_altitude_m}m"
            target_state = ExperimentState.COMPLETED
        elif job.altitude_error_m > job.spec.altitude_tolerance_m:
            job.verdict = "FALSIFIED"
            verdict_reason = f"Final altitude error {job.altitude_error_m:.4f}m exceeded tolerance {job.spec.altitude_tolerance_m}m"
            target_state = ExperimentState.COMPLETED
        else:
            job.verdict = "NOT_FALSIFIED"
            verdict_reason = "All scenario safety constraints satisfied within declared step budget"
            target_state = ExperimentState.COMPLETED

        job.transition_to(target_state, reason=verdict_reason)

        timestamps = [frame["sim_time_s"] for frame in trajectory_records]
        positions = [frame["position_m"] for frame in trajectory_records]
        velocities = [frame["velocity_mps"] for frame in trajectory_records]

        src_code = (
            job.controller.source_code
            if job.controller
            else (job.controller_source or "")
        )
        prompt_meta = (
            {"prompt_version": job.controller.prompt_version}
            if job.controller
            else None
        )

        job.court_record = build_court_record(
            experiment_id=job.id,
            spec=job.spec,
            scenario_seed=job.seed,
            initial_altitude_m=job.initial_altitude_m,
            vertical_disturbance_n=job.vertical_disturbance_n,
            pulse_start_s=job.pulse_start_s,
            pulse_duration_s=job.pulse_duration_s,
            steps=steps,
            timestep_s=float(model.opt.timestep),
            controller_source=src_code,
            controller_model_id=job.model_id,
            prompt_metadata=prompt_meta,
            model_path=self.model_path,
            model_file_hashes=initial_hashes,
            timestamps=timestamps,
            position_m=positions,
            velocity_mps=velocities,
            actions=actions.tolist(),
            integration_states=integration_states.tolist(),
            replay_max_abs_diff=float(job.replay_max_abs_difference or 0.0),
            replay_matched=bool(job.replay_matched),
            flight_verdict=job.verdict,
            verdict_reason=verdict_reason,
            execution_backend=job.execution_backend,
            cleanup_succeeded=job.cleanup_succeeded,
            raw_events=job.event_log,
        )

"""Bounded execution for /missions/run.

Mission runs are CPU-bound MuJoCo loops and, for custom controllers, one
microVM round trip per control step. This module caps how many run at once,
how many may wait, how long a mission may be, and how long a run may take on
the wall clock. Guest resources are always torn down, and the teardown result
is reported rather than assumed.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

# Concurrency and queueing. A request that cannot get a slot within the
# queue wait, or arrives when the waiting room is full, is rejected with 503.
MAX_CONCURRENT_MISSIONS = 2
MAX_WAITING_MISSIONS = 4
MAX_QUEUE_WAIT_S = 30.0

# Work cap. Simulated duration is bounded only by the schema (each stage
# deadline <= 60 s, i.e. up to 30,000 physics steps and, for custom
# controllers, guest exchanges); the wall-clock budget stops runs that take
# too long in practice.
MAX_MISSION_WALL_TIME_S = 90.0
# The microVM's own max-duration is a hard backstop past the wall-time budget.
MICROVM_LEASE_DURATION_S = 120

# Response size caps.
MAX_TRAJECTORY_SAMPLES = 250
MAX_CONTACTS_RETURNED = 200

# Cleanup status values reported to clients.
CLEANUP_NOT_APPLICABLE = "NOT_APPLICABLE"
CLEANUP_SUCCEEDED = "SUCCEEDED"
CLEANUP_FAILED = "FAILED"
CLEANUP_UNKNOWN = "UNKNOWN"


class MissionCapacityError(RuntimeError):
    """No execution slot became available within the queue limits."""


class GuestSetupError(RuntimeError):
    """Guest setup failed; ``cleanup_status`` is the teardown actually observed."""

    def __init__(self, message: str, cleanup_status: str) -> None:
        super().__init__(message)
        self.cleanup_status = cleanup_status


class MissionSlots:
    """Counting semaphore with a bounded waiting room."""

    def __init__(self, max_concurrent: int, max_waiting: int) -> None:
        self.max_concurrent = max_concurrent
        self.max_waiting = max_waiting
        self._semaphore = threading.BoundedSemaphore(max_concurrent)
        self._lock = threading.Lock()
        self._waiting = 0
        self._active = 0
        self.shutdown_event = threading.Event()

    @property
    def active(self) -> int:
        return self._active

    @property
    def waiting(self) -> int:
        return self._waiting

    def acquire(self, timeout_s: float) -> None:
        """Take a slot or raise ``MissionCapacityError``. Pair with ``release()``."""
        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            # No free slot: wait only if the waiting room has space.
            with self._lock:
                if self._waiting >= self.max_waiting:
                    raise MissionCapacityError(
                        f"Mission queue is full ({self._active} running, {self._waiting} waiting)"
                    )
                self._waiting += 1
            try:
                acquired = self._semaphore.acquire(timeout=timeout_s)
            finally:
                with self._lock:
                    self._waiting -= 1
        if not acquired:
            raise MissionCapacityError(
                f"No mission execution slot became free within {timeout_s:.0f}s"
            )
        with self._lock:
            self._active += 1

    def release(self) -> None:
        with self._lock:
            self._active -= 1
        self._semaphore.release()

    @contextmanager
    def slot(self, timeout_s: float) -> Iterator[None]:
        self.acquire(timeout_s)
        try:
            yield
        finally:
            self.release()


mission_slots = MissionSlots(MAX_CONCURRENT_MISSIONS, MAX_WAITING_MISSIONS)


@dataclass
class GuestExecution:
    """Owns the guest stream (and microVM lease, if any) for one mission run.

    Use as a context manager: setup failures, run failures and normal exits
    all go through the same teardown, and ``cleanup_status`` records what was
    actually observed.
    """

    backend: str
    stream: Any = None
    lease: Any = None
    exchanges: int = 0
    cleanup_status: str = CLEANUP_UNKNOWN
    cleanup_errors: list[str] = field(default_factory=list)
    sandbox_name: str | None = None

    def callback(self) -> Callable[[dict[str, Any]], dict[str, Any]]:
        import json

        def guest_callback(obs: dict[str, Any]) -> dict[str, Any]:
            self.exchanges += 1
            raw = self.stream.exchange(obs)
            action = json.loads(raw)
            if not isinstance(action, dict):
                raise ValueError("Controller response must be a JSON object")
            return action

        return guest_callback

    def teardown(self) -> None:
        ok = True
        if self.stream is not None:
            try:
                self.stream.close()
            except Exception as exc:  # noqa: BLE001 - teardown must continue
                ok = False
                self.cleanup_errors.append(f"stream close failed: {type(exc).__name__}")
            process = getattr(self.stream, "process", None)
            if process is not None and process.poll() is None:
                ok = False
                self.cleanup_errors.append("guest subprocess still running after close")
        if self.lease is not None:
            try:
                self.lease.remove()
            except Exception as exc:  # noqa: BLE001
                ok = False
                self.cleanup_errors.append(f"microVM removal failed: {type(exc).__name__}")
            if getattr(self.lease, "cleanup_succeeded", None) is not True:
                ok = False
        self.stream = None
        self.lease = None
        self.cleanup_status = CLEANUP_SUCCEEDED if ok else CLEANUP_FAILED

    def __enter__(self) -> GuestExecution:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.teardown()


def start_microvm_guest(controller_source: str) -> GuestExecution:
    """Create a lease, install the controller and open the guest stream.

    Any failure after the lease exists still tears it down. The returned
    object must be used as a context manager by the caller.
    """
    from domnir.api.jobs import _MicroVMGuestStream
    from domnir.sandbox import SandboxLease

    msb = os.environ.get("DOMNIR_MSB") or shutil.which("msb")
    if not msb:
        raise RuntimeError("Microsandbox executable not found")
    guest = GuestExecution(backend="microvm")
    lease = SandboxLease(Path(msb), duration_seconds=MICROVM_LEASE_DURATION_S)
    guest.sandbox_name = lease.name
    try:
        # SandboxLease.__enter__ removes its own VM if setup fails, but we
        # still record the lease so teardown observes cleanup_succeeded.
        guest.lease = lease
        lease.__enter__()
        lease.install_controller(controller_source.encode("utf-8"))
        guest.stream = _MicroVMGuestStream(lease)
    except Exception as exc:
        guest.teardown()
        raise GuestSetupError(
            f"microVM setup failed ({type(exc).__name__})", guest.cleanup_status
        ) from exc
    except BaseException:
        guest.teardown()
        raise
    return guest


def start_dev_subprocess_guest(controller_source: str) -> GuestExecution:
    from domnir.api.jobs import _IsolatedSubprocessGuestStream

    guest = GuestExecution(backend="subprocess_dev_unisolated")
    try:
        guest.stream = _IsolatedSubprocessGuestStream(controller_source)
    except Exception as exc:
        guest.teardown()
        raise GuestSetupError(
            f"guest subprocess setup failed ({type(exc).__name__})", guest.cleanup_status
        ) from exc
    except BaseException:
        guest.teardown()
        raise
    return guest


def downsample(items: list[Any], max_items: int) -> list[Any]:
    if len(items) <= max_items:
        return list(items)
    stride = -(-len(items) // max_items)  # ceil division keeps len <= max_items
    sampled = items[::stride][:max_items]
    # Always keep the final sample so the reported end state is the real one.
    if sampled[-1] is not items[-1]:
        sampled = sampled[: max_items - 1] + [items[-1]]
    return sampled


class Stopwatch:
    def __init__(self) -> None:
        self.started = time.monotonic()

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started

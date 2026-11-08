"""Bounded execution, teardown and truthful reporting for /missions/run."""

import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import domnir.api.jobs as jobs_module
import domnir.sandbox as sandbox_module
from domnir.api import mission_runner
from domnir.api.app import app
from domnir.api.mission_runner import MissionSlots
from domnir.protocol import ACTION_KEYS

app_module = sys.modules["domnir.api.app"]
client = TestClient(app)

MODEL_PATH = Path(".cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")
needs_model = pytest.mark.skipif(not MODEL_PATH.exists(), reason="MuJoCo cf2.xml model not available")

SHORT_MISSION = {
    "mission_id": "short",
    "world_id": "open-field",
    "stages": [{
        "id": "hold",
        "kind": "waypoint",
        "target_position_m": [0.0, 0.0, 0.05],
        "tolerance_m": 0.5,
        "dwell_s": 0.0,
        "completion_deadline_s": 0.04,
    }],
}

VALID_SOURCE = (
    "def observe(obs):\n"
    "    return {'schema_version': '1.0', 'trial_id': obs['trial_id'], 'step_index': obs['step_index'], "
    + ", ".join(f"'{k}': 0.0" for k in ACTION_KEYS)
    + "}\n"
)


def _action_for(obs):
    import json
    return json.dumps({
        "schema_version": "1.0",
        "trial_id": obs["trial_id"],
        "step_index": obs["step_index"],
        **{k: 0.0 for k in ACTION_KEYS},
    })


class FakeLease:
    instances: list["FakeLease"] = []
    fail_install = False
    fail_remove = False

    def __init__(self, executable, *, duration_seconds=120):
        self.name = "domnir-fake"
        self.duration_seconds = duration_seconds
        self.cleanup_succeeded = None
        self.remove_calls = 0
        self.active = False
        FakeLease.instances.append(self)

    def __enter__(self):
        self.active = True
        return self

    def install_controller(self, source):
        if FakeLease.fail_install:
            raise sandbox_module.SandboxError("copy failed")
        return "digest"

    def remove(self):
        self.remove_calls += 1
        self.active = False
        if FakeLease.fail_remove:
            self.cleanup_succeeded = False
            raise sandbox_module.SandboxError("rm failed")
        self.cleanup_succeeded = True


class FakeStream:
    instances: list["FakeStream"] = []

    def __init__(self, lease, timeout_seconds=2.0):
        self.closed = False
        FakeStream.instances.append(self)

    def exchange(self, observation):
        return _action_for(observation)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_microvm(monkeypatch):
    FakeLease.instances = []
    FakeLease.fail_install = False
    FakeLease.fail_remove = False
    FakeStream.instances = []
    monkeypatch.setattr(app_module, "is_microvm_available", lambda: True)
    monkeypatch.setenv("DOMNIR_MSB", "/usr/bin/true")
    monkeypatch.setattr(sandbox_module, "SandboxLease", FakeLease)
    monkeypatch.setattr(jobs_module, "_MicroVMGuestStream", FakeStream)
    return FakeLease


@pytest.fixture
def fresh_slots(monkeypatch):
    def install(max_concurrent=2, max_waiting=4):
        slots = MissionSlots(max_concurrent, max_waiting)
        monkeypatch.setattr(app_module, "mission_slots", slots)
        return slots
    return install


# --- Truthful reporting ------------------------------------------------------


@needs_model
def test_baseline_gauntlet_reports_real_stage_counts_and_no_guest_claims():
    resp = client.post(
        "/missions/run",
        json={"world_id": "ragnarok-gauntlet", "model_id": "spoofed-model", "controller_type": "spoofed"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_stages"] == 5
    assert len(data["stage_results"]) == 5
    completed = [s for s in data["stage_results"] if s["status"] == "COMPLETED"]
    assert data["stages_completed"] == len(completed)
    for stage in completed:
        assert stage["completed_at_s"] <= stage["completion_deadline_s"] + 1e-9
    if data["stages_completed"] < 5:
        assert data["mission_verdict"] == "NOT_COMPLETED"
        assert data["mission_failure_reason"]

    # The trusted baseline runs no guest: nothing to contain or clean up.
    assert data["execution_backend"] == "host_trusted_kernel"
    assert data["isolation_status"] == "NOT_APPLICABLE"
    assert data["cleanup_status"] == "NOT_APPLICABLE"
    # Client-supplied identity is ignored for the server-side baseline.
    assert data["model_id"] == "baseline_3d"
    assert data["controller_type"] == "baseline_3d"
    assert data["provenance_status"] == "BUILT_IN_BASELINE"

    # Response size is bounded and keeps the true final state.
    assert len(data["trajectory"]) <= mission_runner.MAX_TRAJECTORY_SAMPLES
    assert data["trajectory"][-1]["step_index"] == data["trajectory_samples_total"] - 1


@needs_model
def test_precision_landing_contacts_are_capped_with_true_total():
    data = client.post("/missions/run", json={"world_id": "precision-landing"}).json()
    assert len(data["contacts"]) <= mission_runner.MAX_CONTACTS_RETURNED
    assert data["contacts_total"] >= len(data["contacts"])


# --- Input caps --------------------------------------------------------------


@needs_model
def test_mission_longer_than_ten_seconds_runs(fresh_slots):
    fresh_slots()
    long_mission = {**SHORT_MISSION, "stages": [{**SHORT_MISSION["stages"][0], "completion_deadline_s": 12.0}]}
    resp = client.post("/missions/run", json={"world_id": "open-field", "mission": long_mission})
    assert resp.status_code == 200
    assert resp.json()["trajectory_samples_total"] == 6000


def test_stage_deadline_over_schema_limit_is_rejected():
    too_long = {**SHORT_MISSION, "stages": [{**SHORT_MISSION["stages"][0], "completion_deadline_s": 61.0}]}
    resp = client.post("/missions/run", json={"world_id": "open-field", "mission": too_long})
    assert resp.status_code == 422


def test_too_many_stages_is_rejected():
    stages = [
        {**SHORT_MISSION["stages"][0], "id": f"s{i}", "completion_deadline_s": 0.1 * (i + 1)}
        for i in range(13)
    ]
    resp = client.post("/missions/run", json={"world_id": "open-field", "mission": {**SHORT_MISSION, "stages": stages}})
    assert resp.status_code == 422


def test_too_many_faults_is_rejected():
    gusts = [{"force_x_n": 0.01, "start_s": 0.0, "duration_s": 0.01}] * 17
    resp = client.post(
        "/missions/run",
        json={"world_id": "open-field", "mission": SHORT_MISSION, "faults": {"wind_gusts": gusts}},
    )
    assert resp.status_code == 422


# --- Concurrency, queueing and the event loop --------------------------------


def test_full_queue_returns_503(fresh_slots):
    slots = fresh_slots(max_concurrent=1, max_waiting=0)
    slots.acquire(0)
    try:
        resp = client.post("/missions/run", json={"world_id": "open-field", "mission": SHORT_MISSION})
    finally:
        slots.release()
    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == "10"
    assert "busy" in resp.json()["detail"]


def test_waiting_request_times_out_with_503(fresh_slots, monkeypatch):
    slots = fresh_slots(max_concurrent=1, max_waiting=1)
    monkeypatch.setattr(app_module, "MAX_QUEUE_WAIT_S", 0.05)
    slots.acquire(0)
    try:
        resp = client.post("/missions/run", json={"world_id": "open-field", "mission": SHORT_MISSION})
    finally:
        slots.release()
    assert resp.status_code == 503
    assert slots.active == 0 and slots.waiting == 0


@needs_model
def test_concurrent_missions_are_serialised_by_slots_and_loop_stays_responsive(fresh_slots, monkeypatch):
    slots = fresh_slots(max_concurrent=1, max_waiting=2)
    release = threading.Event()
    running = threading.Event()
    max_seen_active = []
    real_run = app_module.run_mission_simulation

    def gated_run(*args, **kwargs):
        max_seen_active.append(slots.active)
        running.set()
        release.wait(timeout=10)
        return real_run(*args, **kwargs)

    monkeypatch.setattr(app_module, "run_mission_simulation", gated_run)
    results = []

    # Entering the client context makes every request share one event loop,
    # which is what a real ASGI server does. Without it each TestClient call
    # gets its own loop and a blocking endpoint would go unnoticed.
    with TestClient(app) as shared:
        def fire():
            results.append(shared.post("/missions/run", json={"world_id": "open-field", "mission": SHORT_MISSION}))

        threads = [threading.Thread(target=fire) for _ in range(2)]
        for t in threads:
            t.start()
        assert running.wait(timeout=5)

        # While a mission is blocked mid-run, the ASGI loop still serves requests.
        health_result = []
        health_thread = threading.Thread(target=lambda: health_result.append(shared.get("/health")))
        started = time.monotonic()
        health_thread.start()
        health_thread.join(timeout=3)
        responsive = bool(health_result) and time.monotonic() - started < 3.0
        release.set()
        for t in threads:
            t.join(timeout=30)
        health_thread.join(timeout=30)

    assert responsive, "event loop was blocked by a running mission"
    assert health_result[0].status_code == 200

    assert [r.status_code for r in results] == [200, 200]
    assert max(max_seen_active) == 1
    assert slots.active == 0 and slots.waiting == 0


# --- Wall time and cancellation ----------------------------------------------


@needs_model
def test_wall_time_budget_returns_504_and_releases_slot(fresh_slots, monkeypatch):
    slots = fresh_slots()
    monkeypatch.setattr(app_module, "MAX_MISSION_WALL_TIME_S", -1.0)
    resp = client.post("/missions/run", json={"world_id": "open-field", "mission": SHORT_MISSION})
    assert resp.status_code == 504
    assert "wall-time" in resp.json()["detail"]
    assert slots.active == 0


@needs_model
def test_shutdown_cancels_mission_and_tears_down_guest(fresh_slots, fake_microvm):
    slots = fresh_slots()
    slots.shutdown_event.set()
    resp = client.post(
        "/missions/run",
        json={"world_id": "open-field", "mission": SHORT_MISSION, "controller_source": VALID_SOURCE},
    )
    assert resp.status_code == 503
    assert "cancelled" in resp.json()["detail"]
    assert "Guest cleanup: SUCCEEDED" in resp.json()["detail"]
    assert fake_microvm.instances[0].remove_calls >= 1
    assert FakeStream.instances[0].closed is True
    assert slots.active == 0


# --- MicroVM lifecycle (P1-D) ------------------------------------------------


@needs_model
def test_microvm_mission_reports_observed_cleanup(fresh_slots, fake_microvm):
    fresh_slots()
    resp = client.post(
        "/missions/run",
        json={
            "world_id": "open-field",
            "mission": SHORT_MISSION,
            "controller_source": VALID_SOURCE,
            "model_id": "some-model",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_backend"] == "microvm"
    assert data["isolation_status"] == "MICROVM"
    assert data["cleanup_status"] == "SUCCEEDED"
    assert data["provenance_status"] == "UNVERIFIED_ORIGIN"
    assert data["model_id_source"] == "client_reported"
    assert data["controller_exchanges"] == data["trajectory_samples_total"]
    lease = fake_microvm.instances[0]
    assert lease.duration_seconds == mission_runner.MICROVM_LEASE_DURATION_S
    assert lease.remove_calls == 1
    assert FakeStream.instances[0].closed is True


def test_controller_install_failure_still_removes_lease(fresh_slots, fake_microvm):
    slots = fresh_slots()
    fake_microvm.fail_install = True
    resp = client.post(
        "/missions/run",
        json={"world_id": "open-field", "mission": SHORT_MISSION, "controller_source": VALID_SOURCE},
    )
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "setup failed" in detail
    assert "Guest cleanup: SUCCEEDED" in detail
    assert fake_microvm.instances[0].remove_calls == 1
    assert fake_microvm.instances[0].active is False
    assert slots.active == 0


def test_failed_lease_removal_is_reported_not_hidden(fresh_slots, fake_microvm):
    fresh_slots()
    fake_microvm.fail_install = True
    fake_microvm.fail_remove = True
    resp = client.post(
        "/missions/run",
        json={"world_id": "open-field", "mission": SHORT_MISSION, "controller_source": VALID_SOURCE},
    )
    assert resp.status_code == 502
    assert "Guest cleanup: FAILED" in resp.json()["detail"]


@needs_model
def test_successful_run_with_failed_teardown_reports_failed_cleanup(fresh_slots, fake_microvm):
    fresh_slots()
    fake_microvm.fail_remove = True
    data = client.post(
        "/missions/run",
        json={"world_id": "open-field", "mission": SHORT_MISSION, "controller_source": VALID_SOURCE},
    ).json()
    assert data["cleanup_status"] == "FAILED"


@needs_model
def test_malformed_guest_action_is_execution_failure_not_falsification(fresh_slots, fake_microvm, monkeypatch):
    fresh_slots()
    monkeypatch.setattr(FakeStream, "exchange", lambda self, obs: '{"nope": 1}')
    resp = client.post(
        "/missions/run",
        json={"world_id": "open-field", "mission": SHORT_MISSION, "controller_source": VALID_SOURCE},
    )
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "Controller execution failed" in detail
    assert "Guest cleanup: SUCCEEDED" in detail
    assert fake_microvm.instances[0].remove_calls == 1

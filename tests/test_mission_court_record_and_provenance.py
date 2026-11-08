"""3D mission Court Records (P1-E) and server-side controller provenance (P1-G)."""

import copy
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from domnir.api.app import app
from domnir.inference.vultr import InferenceResponse
from domnir.missions.court_record import sha256_of
from domnir.protocol import ACTION_KEYS
from domnir.provenance import ControllerArtifactRegistry

app_module = sys.modules["domnir.api.app"]
MODEL_PATH = Path(".cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")
needs_model = pytest.mark.skipif(not MODEL_PATH.exists(), reason="MuJoCo cf2.xml model not available")
client = TestClient(app)

SHORT_MISSION = {
    "mission_id": "record-test",
    "world_id": "precision-landing",
    "stages": [{
        "id": "hold",
        "kind": "waypoint",
        "target_position_m": [0.8, 0.0, 0.15],
        "tolerance_m": 0.5,
        "dwell_s": 0.0,
        "completion_deadline_s": 0.20,
    }],
}

GUEST_SOURCE = (
    "def observe(obs):\n"
    "    return {'schema_version': '1.0', 'trial_id': obs['trial_id'], 'step_index': obs['step_index'], "
    "'thrust': 0.26487, " + ", ".join(f"'{k}': 0.0" for k in ACTION_KEYS[1:]) + "}\n"
)


def _reseal(record):
    body = {k: v for k, v in record.items() if k != "content_sha256"}
    record["content_sha256"] = sha256_of(body)
    return record


def _verify(record):
    resp = client.post("/court-records/verify", json={"court_record": record})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture(scope="module")
def landing_record():
    data = client.post("/missions/run", json={"world_id": "precision-landing"}).json()
    rec = client.get(data["court_record_url"])
    assert rec.status_code == 200
    return data, rec.json()


# --- P1-E: export and verification -------------------------------------------


@needs_model
def test_mission_run_exports_a_record_that_verifies(landing_record):
    data, record = landing_record
    assert data["court_record_id"] == record["record_id"]
    assert record["schema_version"] == "domnir-mission-court-record-v1"
    assert record["verdicts"]["mission_verdict"] == data["mission_verdict"]
    assert len(record["controller_actions"]) == data["controller_invocations"]
    assert record["checkpoints"]["steps"][-1] == record["simulator"]["physics_steps"]
    assert record["contacts"]["total"] == data["contacts_total"]

    result = _verify(record)
    assert result["verified"] is True, result["errors"]
    assert result["record_type"] == "mission"
    assert result["replay_verdict"] == "MATCHED"
    assert all(result["checks"].values())


@needs_model
def test_record_survives_a_browser_json_round_trip(landing_record, tmp_path):
    _, record = landing_record
    src = tmp_path / "record.json"
    dst = tmp_path / "record_js.json"
    src.write_text(json.dumps(record))
    try:
        subprocess.run(
            ["node", "-e",
             "const fs=require('fs');fs.writeFileSync(process.argv[2],"
             "JSON.stringify(JSON.parse(fs.readFileSync(process.argv[1],'utf8')),null,2));",
             str(src), str(dst)],
            check=True, capture_output=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("node is not available")
    result = _verify(json.loads(dst.read_text()))
    assert result["verified"] is True, result["errors"]


def _tampered(record, mutate, reseal=False):
    r = copy.deepcopy(record)
    mutate(r)
    return _reseal(r) if reseal else r


@needs_model
@pytest.mark.parametrize("name,mutate,failing", [
    ("world geometry",
     lambda r: r["world"]["entities"][0]["pose"]["position_m"].__setitem__(0, 0.5),
     {"content_hash", "world_hash", "world_registry", "compiled_mjcf"}),
    ("trajectory sample",
     lambda r: r["trajectory_samples"][5]["position_m"].__setitem__(2, 0.9),
     {"content_hash", "trajectory_samples"}),
    ("mission verdict",
     lambda r: r["verdicts"].__setitem__("mission_verdict", "NOT_COMPLETED"),
     {"content_hash", "verdicts"}),
    ("controller action",
     lambda r: r["controller_actions"][50].__setitem__(0, 0.10),
     {"content_hash", "checkpoints", "trajectory_samples"}),
    ("stage status",
     lambda r: r["stage_results"][0].__setitem__("status", "TIMED_OUT"),
     {"content_hash", "stage_results"}),
    ("event log",
     lambda r: r["event_log"]["events"][2]["details"].__setitem__("mission_verdict", "COMPLETED_FAKE"),
     {"content_hash", "event_chain"}),
    ("fault schedule",
     lambda r: r.__setitem__("faults", {"wind_gusts": [{"force_x_n": 0.1, "start_s": 0.0, "duration_s": 1.0}]}),
     {"content_hash", "faults_hash", "checkpoints"}),
])
def test_tampering_is_rejected(landing_record, name, mutate, failing):
    _, record = landing_record
    result = _verify(_tampered(record, mutate))
    assert result["verified"] is False, name
    failed = {k for k, ok in result["checks"].items() if not ok}
    assert failing <= failed, f"{name}: expected {failing} to fail, got {failed}"


@needs_model
def test_resealed_tampering_is_still_rejected_by_recomputation(landing_record):
    # Recomputing every hash does not help: the verifier re-flies the
    # mission and recomputes verdicts, stage outcomes and geometry.
    _, record = landing_record
    for mutate, check in [
        (lambda r: r["verdicts"].__setitem__("physical_verdict", "FALSIFIED"), "verdicts"),
        (lambda r: r["stage_results"][-1].__setitem__("completed_at_s", 0.0001), "stage_results"),
    ]:
        r = _tampered(record, mutate, reseal=True)
        result = _verify(r)
        assert result["verified"] is False
        assert result["checks"]["content_hash"] is True
        assert result["checks"][check] is False

    def move_pad(r):
        r["world"]["entities"][0]["pose"]["position_m"][0] = 0.5
        r["world_sha256"] = sha256_of(r["world"])
    result = _verify(_tampered(record, move_pad, reseal=True))
    assert result["verified"] is False
    assert result["checks"]["world_hash"] is True
    assert result["checks"]["world_registry"] is False


def test_unknown_record_id_returns_404():
    assert client.get("/missions/court-records/mcr-doesnotexist").status_code == 404
    assert client.get("/missions/court-records/bad..id").status_code in (400, 404)


@needs_model
def test_cli_verifies_mission_records(landing_record, tmp_path):
    _, record = landing_record
    good = tmp_path / "good.json"
    bad = tmp_path / "bad.json"
    good.write_text(json.dumps(record))
    bad.write_text(json.dumps(_tampered(record, lambda r: r["controller_actions"][3].__setitem__(0, 0.3))))
    ok = subprocess.run([sys.executable, "-m", "domnir.verify", str(good), "--model-path", str(MODEL_PATH)],
                        capture_output=True, text=True, timeout=120)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "Overall Result: PASS" in ok.stdout
    fail = subprocess.run([sys.executable, "-m", "domnir.verify", str(bad), "--model-path", str(MODEL_PATH)],
                          capture_output=True, text=True, timeout=120)
    assert fail.returncode == 1


# --- P1-G: server-side provenance --------------------------------------------


@pytest.fixture
def generated(monkeypatch):
    registry = ControllerArtifactRegistry()
    monkeypatch.setattr(app_module, "controller_artifacts", registry)
    monkeypatch.setattr(app_module, "is_microvm_available", lambda: False)
    monkeypatch.setenv("DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK", "1")
    with patch("domnir.inference.vultr.VultrInferenceClient.chat_completion") as chat, \
         patch("domnir.inference.vultr.VultrInferenceClient.validate_model_id"):
        chat.return_value = InferenceResponse(
            content=GUEST_SOURCE, model="glm-5.3-flash", prompt_tokens=10,
            completion_tokens=20, total_tokens=30, finish_reason="stop",
        )
        resp = client.post("/controllers/generate", json={
            "spec": {"target_altitude_m": 0.1, "mission_duration_s": 0.4},
            "model": "glm-5.3-flash",
        })
    assert resp.status_code == 200, resp.text
    return registry, resp.json()


def _run_custom(source, artifact_id=None, model_id=None):
    resp = client.post("/missions/run", json={
        "world_id": "precision-landing",
        "mission": SHORT_MISSION,
        "controller_source": source,
        "controller_artifact_id": artifact_id,
        "model_id": model_id,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_generation_registers_a_server_artifact(generated):
    registry, gen = generated
    artifact = registry.get(gen["artifact_id"])
    assert artifact is not None
    assert artifact.source_sha256 == gen["source_sha256"]
    assert artifact.model_id == "glm-5.3-flash"
    assert artifact.finish_reason == "stop"


@needs_model
def test_matching_artifact_is_server_confirmed_and_ignores_client_model(generated):
    _, gen = generated
    data = _run_custom(gen["controller"]["source_code"], gen["artifact_id"], model_id="spoofed-model")
    assert data["provenance_status"] == "SERVER_CONFIRMED_GENERATION"
    assert data["model_id"] == "glm-5.3-flash"
    assert data["model_id_source"] == "server_artifact"
    record = client.get(data["court_record_url"]).json()
    assert record["provenance"]["status"] == "SERVER_CONFIRMED_GENERATION"
    assert record["provenance"]["artifact"]["artifact_id"] == gen["artifact_id"]


@needs_model
def test_edited_source_is_user_modified(generated):
    _, gen = generated
    edited = gen["controller"]["source_code"] + "\n# tuned by hand\n"
    data = _run_custom(edited, gen["artifact_id"], model_id="glm-5.3-flash")
    assert data["provenance_status"] == "USER_MODIFIED"
    assert data["model_id_source"] == "server_artifact_modified"


@needs_model
def test_claimed_model_without_artifact_is_unverified(generated):
    _, gen = generated
    data = _run_custom(gen["controller"]["source_code"], None, model_id="glm-5.3-flash")
    assert data["provenance_status"] == "UNVERIFIED_ORIGIN"
    assert data["model_id_source"] == "client_reported"
    data = _run_custom(gen["controller"]["source_code"], "ctrl-unknown", model_id="glm-5.3-flash")
    assert data["provenance_status"] == "UNVERIFIED_ORIGIN"


def test_artifact_registry_is_bounded():
    registry = ControllerArtifactRegistry(max_artifacts=3)
    ids = [
        registry.register(source_code=f"# {i}", model_id="m", requested_model="m",
                          prompt_version="v1", reasoning_effort="minimal").artifact_id
        for i in range(5)
    ]
    assert registry.get(ids[0]) is None and registry.get(ids[1]) is None
    assert all(registry.get(i) is not None for i in ids[2:])

"""Offline-checkable provenance: Ed25519 record seals and generation attestations."""

import base64
import copy
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from domnir.api.app import app
from domnir.inference.vultr import InferenceResponse
from domnir.missions.court_record import sha256_of
from domnir.protocol import ACTION_KEYS
from domnir.provenance import ControllerArtifactRegistry
from domnir.signing import (
    AUTHENTIC,
    INVALID_SIGNATURE,
    SIGNED_UNTRUSTED_KEY,
    UNSIGNED,
    ProvenanceSigner,
    check_signature,
    parse_trusted_keys,
)

app_module = sys.modules["domnir.api.app"]
MODEL_PATH = Path(".cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")
needs_model = pytest.mark.skipif(not MODEL_PATH.exists(), reason="MuJoCo cf2.xml model not available")
client = TestClient(app)

SHORT_MISSION = {
    "mission_id": "offline-prov",
    "world_id": "open-field",
    "stages": [{"id": "hold", "kind": "waypoint", "target_position_m": [0.0, 0.0, 0.05],
                "tolerance_m": 0.5, "dwell_s": 0.0, "completion_deadline_s": 0.10}],
}
GUEST_SOURCE = (
    "def observe(obs):\n"
    "    return {'schema_version': '1.0', 'trial_id': obs['trial_id'], 'step_index': obs['step_index'], "
    "'thrust': 0.26487, " + ", ".join(f"'{k}': 0.0" for k in ACTION_KEYS[1:]) + "}\n"
)


def _server_keys():
    return client.get("/provenance/keys").json()


def _verify(record):
    resp = client.post("/court-records/verify", json={"court_record": record})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _attacker_reseal(record, attacker):
    body = {k: v for k, v in record.items() if k not in ("content_sha256", "record_signature")}
    record["content_sha256"] = sha256_of(body)
    record["record_signature"] = attacker.sign({
        "schema_version": record["schema_version"],
        "record_id": record["record_id"],
        "content_sha256": record["content_sha256"],
    })
    return record


@pytest.fixture(scope="module")
def baseline_record():
    data = client.post("/missions/run", json={"world_id": "open-field", "mission": SHORT_MISSION}).json()
    return client.get(data["court_record_url"]).json()


@pytest.fixture
def confirmed_record(monkeypatch):
    monkeypatch.setattr(app_module, "controller_artifacts", ControllerArtifactRegistry())
    monkeypatch.setattr(app_module, "is_microvm_available", lambda: False)
    monkeypatch.setenv("DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK", "1")
    with patch("domnir.inference.vultr.VultrInferenceClient.chat_completion") as chat, \
         patch("domnir.inference.vultr.VultrInferenceClient.validate_model_id"):
        chat.return_value = InferenceResponse(
            content=GUEST_SOURCE, model="glm-5.3-flash", prompt_tokens=1,
            completion_tokens=1, total_tokens=2, finish_reason="stop",
        )
        gen = client.post("/controllers/generate", json={
            "spec": {"target_altitude_m": 0.1, "mission_duration_s": 0.4}, "model": "glm-5.3-flash",
        }).json()
    run = client.post("/missions/run", json={
        "world_id": "open-field", "mission": SHORT_MISSION,
        "controller_source": gen["controller"]["source_code"],
        "controller_artifact_id": gen["artifact_id"],
    }).json()
    assert run["provenance_status"] == "SERVER_CONFIRMED_GENERATION"
    return gen, client.get(run["court_record_url"]).json()


# --- Signing primitives -------------------------------------------------------


def test_signature_round_trip_and_trust_levels():
    signer = ProvenanceSigner(Ed25519PrivateKey.generate(), ephemeral=False)
    payload = {"a": 1, "b": [0.5, "x"]}
    block = signer.sign(payload)
    trusted = {signer.info.key_id: signer.info.public_key}

    assert check_signature(payload, block, trusted)[0] == AUTHENTIC
    assert check_signature(payload, block, None)[0] == SIGNED_UNTRUSTED_KEY
    assert check_signature({"a": 2, "b": [0.5, "x"]}, block, trusted)[0] == INVALID_SIGNATURE
    assert check_signature(payload, None, trusted)[0] == UNSIGNED

    swapped = dict(block, public_key=ProvenanceSigner(Ed25519PrivateKey.generate(), ephemeral=True).info.public_key)
    assert check_signature(payload, swapped, trusted)[0] == INVALID_SIGNATURE


def test_signing_key_loads_from_env(monkeypatch):
    seed = base64.b64encode(bytes(range(32))).decode()
    monkeypatch.setenv("DOMNIR_PROVENANCE_SIGNING_KEY", seed)
    a, b = ProvenanceSigner.from_env(), ProvenanceSigner.from_env()
    assert a.info.key_id == b.info.key_id and a.info.ephemeral is False
    monkeypatch.setenv("DOMNIR_PROVENANCE_SIGNING_KEY", base64.b64encode(b"short").decode())
    with pytest.raises(ValueError):
        ProvenanceSigner.from_env()
    monkeypatch.delenv("DOMNIR_PROVENANCE_SIGNING_KEY")
    assert ProvenanceSigner.from_env().info.ephemeral is True


def test_generate_key_cli_prints_a_usable_seed():
    out = subprocess.run([sys.executable, "-m", "domnir.signing", "generate-key"],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    seed = out.splitlines()[0].split("=", 1)[1]
    assert len(base64.b64decode(seed)) == 32


def test_keys_endpoint_publishes_the_signing_key():
    keys = _server_keys()
    assert len(keys["keys"]) == 1
    entry = keys["keys"][0]
    assert entry["algorithm"] == "Ed25519"
    assert parse_trusted_keys([json.dumps(keys)]) == {entry["key_id"]: entry["public_key"]}


# --- Record seals ---------------------------------------------------------------


@needs_model
def test_records_are_sealed_and_authentic_on_the_issuing_server(baseline_record):
    sig = baseline_record["record_signature"]
    assert sig["key_id"] == _server_keys()["keys"][0]["key_id"]
    result = _verify(baseline_record)
    assert result["verified"] is True, result["errors"]
    assert result["authenticity"] == AUTHENTIC
    assert result["checks"]["record_signature"] and result["checks"]["provenance"]


@needs_model
def test_offline_cli_authenticates_only_with_a_pinned_key(baseline_record, tmp_path):
    rec = tmp_path / "rec.json"
    keys = tmp_path / "keys.json"
    rec.write_text(json.dumps(baseline_record))
    keys.write_text(json.dumps(_server_keys()))
    cmd = [sys.executable, "-m", "domnir.verify", str(rec), "--model-path", str(MODEL_PATH), "--json"]

    pinned = subprocess.run(cmd + ["--trusted-key", str(keys)], capture_output=True, text=True, timeout=120)
    assert pinned.returncode == 0, pinned.stdout + pinned.stderr
    assert json.loads(pinned.stdout)["authenticity"] == AUTHENTIC

    unpinned = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert unpinned.returncode == 0
    assert json.loads(unpinned.stdout)["authenticity"] == SIGNED_UNTRUSTED_KEY

    other = ProvenanceSigner(Ed25519PrivateKey.generate(), ephemeral=False).info.public_key
    wrong = subprocess.run(cmd + ["--trusted-key", other], capture_output=True, text=True, timeout=120)
    assert json.loads(wrong.stdout)["authenticity"] == SIGNED_UNTRUSTED_KEY


@needs_model
def test_stripped_or_broken_seal_fails(baseline_record):
    stripped = copy.deepcopy(baseline_record)
    stripped.pop("record_signature")
    result = _verify(stripped)
    assert result["verified"] is False and result["authenticity"] == UNSIGNED

    broken = copy.deepcopy(baseline_record)
    broken["record_signature"]["signature"] = base64.b64encode(b"\0" * 64).decode()
    result = _verify(broken)
    assert result["verified"] is False and result["authenticity"] == INVALID_SIGNATURE


@needs_model
def test_attacker_cannot_claim_server_provenance(baseline_record):
    # Forge a "generated by glm" claim with an attestation and seal signed by
    # the attacker's own key. The claim is self-consistent, but the record is
    # never AUTHENTIC against the server's key.
    attacker = ProvenanceSigner(Ed25519PrivateKey.generate(), ephemeral=False)
    forged = copy.deepcopy(baseline_record)
    forged["controller"]["source_code"] = None
    attestation = {"type": "domnir-controller-generation-attestation-v1", "model_id": "glm-5.3-flash",
                   "source_sha256": forged["controller"]["source_sha256"]}
    forged["provenance"] = {
        "status": "SERVER_CONFIRMED_GENERATION", "model_id": "glm-5.3-flash", "model_id_source": "server_artifact",
        "artifact": None, "attestation": attestation, "attestation_signature": attacker.sign(attestation),
    }
    result = _verify(_attacker_reseal(forged, attacker))
    assert result["authenticity"] == SIGNED_UNTRUSTED_KEY
    assert result["signer_key_id"] == attacker.info.key_id

    # Splicing the attacker's attestation under a different seal key fails outright.
    other = ProvenanceSigner(Ed25519PrivateKey.generate(), ephemeral=False)
    result = _verify(_attacker_reseal(copy.deepcopy(forged), other))
    assert result["checks"]["provenance"] is False
    assert result["verified"] is False


# --- Generation attestations ---------------------------------------------------


@needs_model
def test_server_confirmed_record_carries_a_valid_attestation(confirmed_record):
    gen, record = confirmed_record
    trusted = parse_trusted_keys([json.dumps(_server_keys())])
    prov = record["provenance"]
    assert check_signature(prov["attestation"], prov["attestation_signature"], trusted)[0] == AUTHENTIC
    assert prov["attestation"]["source_sha256"] == record["controller"]["source_sha256"]
    assert gen["attestation"] == prov["attestation"]
    result = _verify(record)
    assert result["verified"] is True and result["authenticity"] == AUTHENTIC, result["errors"]


@needs_model
def test_editing_the_signed_attestation_is_detected(confirmed_record):
    _, record = confirmed_record
    r = copy.deepcopy(record)
    r["provenance"]["attestation"]["model_id"] = "deepseek-v4.1-flash-1017"
    r["provenance"]["model_id"] = "deepseek-v4.1-flash-1017"
    result = _verify(r)
    assert result["verified"] is False
    assert result["checks"]["provenance"] is False

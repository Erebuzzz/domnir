"""Mission Court Records must verify on a machine that keeps the model elsewhere."""

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from domnir.api.app import app
from domnir.missions.court_record import verify_mission_court_record
from domnir.missions.simulator import portable_mjcf_fingerprint

MODEL_PATH = Path(".cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")
pytestmark = pytest.mark.skipif(not MODEL_PATH.exists(), reason="MuJoCo cf2.xml model not available")
client = TestClient(app)


@pytest.fixture(scope="module")
def record():
    data = client.post("/missions/run", json={"world_id": "precision-landing"}).json()
    return client.get(data["court_record_url"]).json()


@pytest.fixture
def relocated_model(tmp_path):
    dest = tmp_path / "somewhere" / "else" / "bitcraze_crazyflie_2"
    shutil.copytree(MODEL_PATH.parent, dest)
    return dest / "cf2.xml"


def test_fingerprint_ignores_the_host_mesh_path():
    base = '<mujoco><compiler meshdir="{}" autolimits="true"/><worldbody/></mujoco>'
    a = portable_mjcf_fingerprint(base.format("/home/domnir/menagerie/bitcraze_crazyflie_2/assets"))
    b = portable_mjcf_fingerprint(base.format("/tmp/x/y/bitcraze_crazyflie_2/assets"))
    c = portable_mjcf_fingerprint(base.format("assets"))
    assert a == b == c
    # Geometry still matters.
    changed = '<mujoco><compiler meshdir="assets"/><worldbody><geom type="box" size="1 1 1"/></worldbody></mujoco>'
    assert portable_mjcf_fingerprint(changed) != c


def test_record_verifies_with_the_model_at_a_different_path(record, relocated_model):
    result = verify_mission_court_record(copy.deepcopy(record), model_path=relocated_model)
    assert result["verified"] is True, result["errors"]
    assert result["checks"]["compiled_mjcf"] is True


def test_cli_verifies_from_a_different_checkout_path(record, relocated_model, tmp_path):
    rec = tmp_path / "record.json"
    rec.write_text(json.dumps(record))
    out = subprocess.run(
        [sys.executable, "-m", "domnir.verify", str(rec), "--model-path", str(relocated_model)],
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "[PASS] compiled_mjcf" in out.stdout


def test_changed_world_geometry_still_fails_the_compiled_scene_check(record, relocated_model):
    from domnir.missions.court_record import sha256_of
    r = copy.deepcopy(record)
    r["world"]["entities"][0]["pose"]["position_m"][0] += 0.2
    r["world_sha256"] = sha256_of(r["world"])
    result = verify_mission_court_record(r, model_path=relocated_model)
    assert result["verified"] is False
    assert result["checks"]["compiled_mjcf"] is False


def test_legacy_record_without_portable_hash_falls_back_to_the_raw_hash(record):
    legacy = copy.deepcopy(record)
    legacy["simulator"].pop("compiled_mjcf_portable_sha256")
    # Same path as the issuing host, so the raw hash still matches; the
    # content hash and seal no longer do because the record was edited.
    result = verify_mission_court_record(legacy, model_path=MODEL_PATH)
    assert result["checks"]["compiled_mjcf"] is True
    assert result["checks"]["content_hash"] is False

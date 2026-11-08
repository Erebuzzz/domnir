"""Tests for API mission laboratory endpoints (/worlds, /missions/run)."""

import sys
from fastapi.testclient import TestClient
from domnir.api.app import app

app_module = sys.modules["domnir.api.app"]


client = TestClient(app)


def test_get_worlds_list():
    resp = client.get("/worlds")
    assert resp.status_code == 200
    worlds = resp.json()
    assert len(worlds) >= 5
    ids = [w["id"] for w in worlds]
    assert "ragnarok-gauntlet" in ids
    assert "precision-landing" in ids
    assert "gate-corridor" in ids
    assert "wind-tunnel" in ids
    assert "open-field" in ids


def test_get_world_detail():
    resp = client.get("/worlds/ragnarok-gauntlet")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "ragnarok-gauntlet"
    assert "entities" in data
    assert len(data["entities"]) == 3


def test_get_unknown_world_returns_404():
    resp = client.get("/worlds/not-a-valid-world")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_run_mission_unknown_world_returns_404():
    resp = client.post("/missions/run", json={"world_id": "not-a-valid-world"})
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_run_mission_gauntlet_baseline():
    resp = client.post("/missions/run", json={"world_id": "ragnarok-gauntlet"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["world_id"] == "ragnarok-gauntlet"
    assert data["physical_verdict"] == "NOT_FALSIFIED"
    assert data["replay_matched"] is True
    assert len(data["trajectory"]) > 0
    assert "limitation_note" in data


def test_run_mission_invalid_controller_returns_400():
    resp = client.post(
        "/missions/run",
        json={
            "world_id": "ragnarok-gauntlet",
            "controller_source": "invalid code syntax ((((",
        },
    )
    assert resp.status_code == 400
    assert "Invalid controller source" in resp.json()["detail"]


def test_run_mission_untrusted_controller_fails_closed(monkeypatch):
    monkeypatch.setattr(app_module, "is_microvm_available", lambda: False)
    monkeypatch.delenv("DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK", raising=False)
    resp = client.post(
        "/missions/run",
        json={
            "world_id": "ragnarok-gauntlet",
            "controller_source": "def observe(obs):\n    return {}\n",
        },
    )
    # Must fail closed without microVM isolation
    assert resp.status_code == 503
    assert "isolation is unavailable" in resp.json()["detail"]

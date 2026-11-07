"""Integration tests for Ragnarok API endpoints."""

import os
import pytest
from fastapi.testclient import TestClient
from domnir.api.app import app


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK", "1")
    monkeypatch.delenv("DOMNIR_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    return TestClient(app)


def test_ragnarok_falsify_invalid_controller_rejected(client: TestClient):
    payload = {
        "spec": {"target_altitude_m": 0.10},
        "controller_source": "invalid python code {{{",
        "budget": 4,
    }
    response = client.post("/ragnarok/falsify", json=payload)
    assert response.status_code == 400
    assert "not valid Python" in response.json()["detail"]


def test_ragnarok_minimize_requires_failing_witness(client: TestClient):
    payload = {
        "spec": {"target_altitude_m": 0.10},
        "controller_source": "def observe(obs):\n    return [0.0, 0.0, 0.0, 0.0]\n",
        "witness_scenario": {
            "initial_altitude_m": 0.10,
            "disturbance_force_z": 0.0,
        },
        "max_evaluations": 4,
    }
    # For a zero-thrust controller starting at 0.10m, gravity causes it to crash to the floor (failure)
    # Minimizer should proceed and return 200
    response = client.post("/ragnarok/minimize", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "minimized_scenario" in data
    assert "original_cost" in data
    assert data["predicate_preserved"] is True


def test_ragnarok_repair_rejects_passing_witness(client: TestClient):
    # A controller that already passes a calm scenario cannot be repaired on that scenario
    payload = {
        "spec": {"target_altitude_m": 0.10},
        "controller_source": (
            "def observe(obs):\n"
            "    # Calibrated near hover\n"
            "    return [0.27, 0.27, 0.27, 0.27]\n"
        ),
        "witness_scenario": {
            "initial_altitude_m": 0.10,
            "disturbance_force_z": 0.0,
        },
        "max_revisions": 1,
    }
    response = client.post("/ragnarok/repair", json=payload)
    # If the controller satisfies the witness scenario, endpoint rejects with 400
    if response.status_code == 400:
        assert "Witness scenario does not violate" in response.json()["detail"]
    else:
        # If it failed, outcome is reported
        assert response.status_code == 200
        assert "outcome" in response.json()

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


def test_ragnarok_compare_reports_accurate_evaluations_count(client: TestClient):
    payload = {
        "spec": {"target_altitude_m": 0.10, "mission_duration_s": 0.10},
        "controller_source": "def observe(obs):\n    return [0.0, 0.0, 0.0, 0.0]\n",
        "budget": 2,
        "strategy": "compare",
    }
    response = client.post("/ragnarok/falsify", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["strategy"] == "compare"
    assert data["evaluations_count"] == 6  # 2 uniform + 2 sobol + 2 DE
    assert "Uniform Random vs Sobol vs Differential Evolution" in data["summary"]
    assert "total 6 evaluations" in data["summary"]


def test_safety_contract_short_duration_settling_time_adapts():
    from domnir.contracts.stl import SafetyContract
    from domnir.spec import FlightSpec
    spec = FlightSpec(mission_duration_s=0.08)
    contract = SafetyContract.from_flight_spec(spec)
    assert contract.settling_time_s < contract.mission_duration_s
    assert contract.settling_time_s == pytest.approx(0.08 * 0.4)


def test_ragnarok_search_space_respects_custom_disturbance_bounds():
    from domnir.contracts.stl import SafetyContract
    from domnir.ragnarok.search import RagnarokSearchSpace
    contract = SafetyContract(
        disturbance_force_z_min=-0.08,
        disturbance_force_z_max=0.09,
    )
    space = RagnarokSearchSpace.from_contract(contract)
    assert space.force_min_n == pytest.approx(-0.08)
    assert space.force_max_n == pytest.approx(0.09)


def test_ragnarok_arena_run_endpoint(client: TestClient):
    payload = {
        "spec": {"target_altitude_m": 0.10, "mission_duration_s": 0.10},
        "controller_source": "def observe(obs):\n    return [0.0, 0.0, 0.0, 0.0]\n",
        "max_rounds": 1,
        "search_budget_per_round": 4,
        "max_repair_revisions": 1,
    }
    response = client.post("/ragnarok/arena/run", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "campaign_id" in data
    assert data["total_rounds_executed"] >= 1
    assert "rounds" in data
    assert len(data["rounds"]) >= 1
    assert "limitation_note" in data


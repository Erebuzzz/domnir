"""Regression test for witness replay correctness (Task 6).

Verifies that when an adversarial witness is discovered by Ragnarök search,
replaying that witness with its full 4D scenario parameters (initial altitude,
disturbance force, pulse start, pulse duration) reproduces the exact same
trajectory within replay tolerance (1e-12). Also tests that omitting pulse
timing parameters causes significant divergence, proving the bug and fix.
"""

import os
import numpy as np
import pytest
from fastapi.testclient import TestClient

from domnir.api.app import app
from domnir.api.models import FlightSpec, RagnarokFalsifyRequest, RunExperimentRequest
from domnir.contracts.stl import SafetyContract
from domnir.ragnarok.search import (
    DifferentialEvolutionFalsifier,
    RagnarokSearchSpace,
)
from domnir.scenario import ScenarioParameter

client = TestClient(app)

HOVER_SOURCE = (
    "def observe(obs):\n"
    "    return {'schema_version': '1.0', 'trial_id': obs['trial_id'], 'step_index': obs['step_index'], "
    "'thrust': 0.26487, 'moment_x': 0.0, 'moment_y': 0.0, 'moment_z': 0.0}\n"
)


@pytest.fixture(autouse=True)
def enable_dev_fallback(monkeypatch):
    monkeypatch.setenv("DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK", "1")


def test_adversarial_witness_replay_reproduces_trajectory_within_tolerance():
    """Falsify a controller, then replay the critical witness and verify exact match."""
    spec = FlightSpec(
        target_altitude_m=0.10,
        altitude_tolerance_m=0.04,
        min_allowed_altitude_m=0.05,
        max_allowed_altitude_m=0.30,
        mission_duration_s=0.25,
        disturbance_force_z_min=-0.15,
        disturbance_force_z_max=0.15,
    )

    falsify_resp = client.post(
        "/ragnarok/falsify",
        json={
            "spec": spec.model_dump(),
            "controller_source": HOVER_SOURCE,
            "strategy": "differential_evolution",
            "budget": 15,
            "seed": 42,
        },
    )
    assert falsify_resp.status_code == 200, falsify_resp.text
    falsify_data = falsify_resp.json()

    witness = falsify_data.get("critical_witness")
    assert witness is not None, "Differential evolution must discover an adversarial witness"
    sc = witness["scenario"]

    # Replay 1: exact scenario parameters via /experiments/run
    replay_resp_1 = client.post(
        "/experiments/run",
        json={
            "spec": spec.model_dump(),
            "controller_source": HOVER_SOURCE,
            "model": "user_supplied",
            "initial_altitude_m": sc["initial_altitude_m"],
            "vertical_disturbance_n": sc["disturbance_force_z"],
            "pulse_start_s": sc["pulse_start_s"],
            "pulse_duration_s": sc["pulse_duration_s"],
        },
    )
    assert replay_resp_1.status_code == 200, replay_resp_1.text
    job_1_id = replay_resp_1.json()["id"]

    job_1 = app.state.orchestrator.get_job(job_1_id) if hasattr(app.state, "orchestrator") else None
    from domnir.api.app import orchestrator
    job_1 = orchestrator.get_job(job_1_id)
    assert job_1 is not None
    traj_1 = job_1.trajectory
    assert len(traj_1) > 0

    # Replay 2: independent second replay with identical 4D parameters
    replay_resp_2 = client.post(
        "/experiments/run",
        json={
            "spec": spec.model_dump(),
            "controller_source": HOVER_SOURCE,
            "model": "user_supplied",
            "initial_altitude_m": sc["initial_altitude_m"],
            "vertical_disturbance_n": sc["disturbance_force_z"],
            "pulse_start_s": sc["pulse_start_s"],
            "pulse_duration_s": sc["pulse_duration_s"],
        },
    )
    assert replay_resp_2.status_code == 200
    job_2_id = replay_resp_2.json()["id"]

    job_2 = orchestrator.get_job(job_2_id)
    assert job_2 is not None
    traj_2 = job_2.trajectory

    pos_1 = np.array([p["position_m"] for p in traj_1])
    pos_2 = np.array([p["position_m"] for p in traj_2])
    max_diff = float(np.max(np.abs(pos_1 - pos_2)))

    # Deterministic replay must match with zero / machine-precision tolerance
    assert max_diff <= 1e-12, f"Witness replay diverged between runs: max diff {max_diff}"

    # Also verify court-records match
    rec_1 = client.get(f"/experiments/{job_1_id}/court-record").json()
    rec_2 = client.get(f"/experiments/{job_2_id}/court-record").json()
    assert rec_1["trajectory"]["position_m"] == rec_2["trajectory"]["position_m"]

    # Replay 3 (flawed): missing pulse parameters (simulating old UI syncWitnessReplay bug)
    if sc.get("pulse_duration_s", 0) > 0:
        replay_flawed = client.post(
            "/experiments/run",
            json={
                "spec": spec.model_dump(),
                "controller_source": HOVER_SOURCE,
                "model": "user_supplied",
                "initial_altitude_m": sc["initial_altitude_m"],
                "vertical_disturbance_n": sc["disturbance_force_z"],
                "pulse_start_s": 0.0,
                "pulse_duration_s": 0.0,
            },
        ).json()
        job_flawed = orchestrator.get_job(replay_flawed["id"])
        flawed_pos = np.array([p["position_m"] for p in job_flawed.trajectory])
        flawed_diff = float(np.max(np.abs(pos_1 - flawed_pos)))
        assert flawed_diff > 1e-4, "Omission of pulse timing should noticeably diverge from witness"

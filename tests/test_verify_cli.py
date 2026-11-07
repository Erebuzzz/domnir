"""Tests for Court Record Multi-Tier Independent Verifier and CLI."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from domnir.api.jobs import get_default_model_path
from domnir.court_record import SCHEMA_VERSION, build_court_record
from domnir.spec import FlightSpec
from domnir.verify import (
    CourtRecordVerifier,
    TierLevel,
    VerificationReport,
    verify_court_record_cli,
)
from tests.test_court_record import SAMPLE_CONTROLLER, run_test_simulation


@pytest.fixture
def valid_court_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv("DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK", "1")
    model_path = get_default_model_path()
    sim = run_test_simulation(model_path, steps=5)
    spec = FlightSpec(
        target_altitude_m=0.1,
        altitude_tolerance_m=0.05,
        min_allowed_altitude_m=0.05,
        max_allowed_altitude_m=0.5,
        mission_duration_s=0.02,
        dt_s=0.002,
    )
    raw_events = [
        {"event_type": "job_created", "source": "trusted_host", "details": {"id": "test-exp"}},
        {"event_type": "simulation_started", "source": "trusted_host", "details": {"steps": 5}},
        {"event_type": "simulation_completed", "source": "trusted_host", "details": {"diff": 0.0}},
        {"event_type": "cleanup_finished", "source": "trusted_host", "details": {"status": "ok"}},
    ]

    record = build_court_record(
        experiment_id="test-exp-001",
        spec=spec,
        scenario_seed=42,
        initial_altitude_m=0.15,
        vertical_disturbance_n=0.0,
        steps=sim["steps"],
        timestep_s=sim["timestep_s"],
        controller_source=SAMPLE_CONTROLLER,
        controller_model_id="glm-5.3-flash",
        prompt_metadata={"prompt_version": "v1"},
        model_path=model_path,
        timestamps=sim["timestamps"],
        position_m=sim["positions"],
        velocity_mps=sim["velocities"],
        actions=sim["actions"],
        integration_states=sim["integration_states"],
        replay_max_abs_diff=0.0,
        replay_matched=True,
        flight_verdict="NOT_FALSIFIED",
        verdict_reason="All constraints satisfied",
        execution_backend="trusted_simulator",
        cleanup_succeeded=True,
        raw_events=raw_events,
    )
    return record


def test_l0_structural_validation_on_valid_fixture(valid_court_record):
    verifier = CourtRecordVerifier()
    report = verifier.verify(valid_court_record, max_tier="L0")

    assert report.verified is True
    assert report.tampered is False
    assert "L0" in report.tiers
    assert report.tiers["L0"].passed is True
    assert report.tiers["L0"].tampered is False
    assert len(report.errors) == 0


def test_full_l0_to_l3_verification_on_valid_fixture(valid_court_record):
    verifier = CourtRecordVerifier()
    report = verifier.verify(valid_court_record, max_tier="L3")

    assert report.verified is True
    assert report.tampered is False
    assert len(report.tiers) == 4
    for tier in ("L0", "L1", "L2", "L3"):
        assert report.tiers[tier].passed is True
        assert report.tiers[tier].tampered is False

    assert report.tiers["L1"].details["max_divergence_m"] <= 1.00e-12
    assert report.tiers["L2"].details["steps_verified"] == 5
    assert report.tiers["L3"].details["trusted_events_count"] == 4


def test_tamper_detection_modified_action(valid_court_record):
    tampered = copy.deepcopy(valid_court_record)
    tampered["trajectory"]["actions"][0][0] += 0.05

    verifier = CourtRecordVerifier()
    report = verifier.verify(tampered)

    assert report.verified is False
    assert report.tampered is True
    assert any("Trajectory SHA-256 mismatch" in err or "Action mismatch" in err for err in report.tamper_details)


def test_tamper_detection_altered_state(valid_court_record):
    tampered = copy.deepcopy(valid_court_record)
    tampered["trajectory"]["position_m"][1][2] += 0.20

    verifier = CourtRecordVerifier()
    report = verifier.verify(tampered)

    assert report.verified is False
    assert report.tampered is True
    assert any("Trajectory SHA-256 mismatch" in err or "Physics replay divergence" in err for err in report.tamper_details)


def test_tamper_detection_altered_timestamps(valid_court_record):
    tampered = copy.deepcopy(valid_court_record)
    tampered["trajectory"]["timestamps"][2] = -1.0

    verifier = CourtRecordVerifier()
    report = verifier.verify(tampered)

    assert report.verified is False
    assert report.tampered is True
    assert any("timestamps" in err.lower() or "trajectory sha-256 mismatch" in err.lower() for err in report.tamper_details)


def test_tamper_detection_corrupted_controller_source(valid_court_record):
    tampered = copy.deepcopy(valid_court_record)
    tampered["controller"]["source_code"] += "\n# altered"

    verifier = CourtRecordVerifier()
    report = verifier.verify(tampered)

    assert report.verified is False
    assert report.tampered is True
    assert any("Controller SHA-256 mismatch" in err for err in report.tamper_details)


def test_tamper_detection_broken_event_chain(valid_court_record):
    tampered = copy.deepcopy(valid_court_record)
    tampered["event_log"]["events"][1]["details"]["tampered_key"] = "tampered_value"

    verifier = CourtRecordVerifier()
    report = verifier.verify(tampered)

    assert report.verified is False
    assert report.tampered is True
    assert any("Broken event chain" in err for err in report.tamper_details)


def test_cli_exit_code_zero_on_valid_record(valid_court_record, tmp_path: Path):
    rec_file = tmp_path / "valid_record.json"
    rec_file.write_text(json.dumps(valid_court_record), encoding="utf-8")

    exit_code = verify_court_record_cli([str(rec_file)])
    assert exit_code == 0


def test_cli_exit_code_one_on_tampered_record(valid_court_record, tmp_path: Path):
    tampered = copy.deepcopy(valid_court_record)
    tampered["trajectory"]["actions"][0][0] += 0.1

    rec_file = tmp_path / "tampered_record.json"
    rec_file.write_text(json.dumps(tampered), encoding="utf-8")

    exit_code = verify_court_record_cli([str(rec_file)])
    assert exit_code == 1


def test_cli_exit_code_two_on_missing_file(tmp_path: Path):
    missing_file = tmp_path / "non_existent.json"
    exit_code = verify_court_record_cli([str(missing_file)])
    assert exit_code == 2


def test_cli_exit_code_two_on_invalid_json(tmp_path: Path):
    bad_json_file = tmp_path / "broken.json"
    bad_json_file.write_text("{ incomplete json ...", encoding="utf-8")

    exit_code = verify_court_record_cli([str(bad_json_file)])
    assert exit_code == 2


def test_cli_json_output_mode(valid_court_record, tmp_path: Path, capsys):
    rec_file = tmp_path / "record.json"
    rec_file.write_text(json.dumps(valid_court_record), encoding="utf-8")

    exit_code = verify_court_record_cli([str(rec_file), "--json"])
    assert exit_code == 0

    captured = capsys.readouterr()
    parsed_json = json.loads(captured.out)
    assert parsed_json["verified"] is True
    assert parsed_json["tampered"] is False
    assert "L0" in parsed_json["tiers"]
    assert "L1" in parsed_json["tiers"]
    assert "L2" in parsed_json["tiers"]
    assert "L3" in parsed_json["tiers"]

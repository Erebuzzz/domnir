"""Replay a saved feasibility campaign without executing its controller."""

import argparse
import hashlib
import json
from pathlib import Path

from domnir.campaign import REPLAY_TOLERANCE, build_record
from domnir.event_log import verify_completed_campaign_events
from domnir.fixture_trial import GUEST_RUNNER
from domnir.replay import replay_saved_trajectory
from domnir.sandbox import validate_controller_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--controller", type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.record.read_text(encoding="utf-8"))
    if record["schema_version"] != "feasibility-2":
        raise ValueError(
            "This verifier requires a full-integration-state feasibility-2 record"
        )
    with args.controller.open("rb") as source_file:
        source_hash = validate_controller_source(source_file.read(32769))
    if source_hash != record["controller_sha256"]:
        raise ValueError("Controller source does not match the record")
    campaign = record["campaign"]
    recomputed = build_record(campaign["seed"], source_hash, campaign["scenarios"])
    for key in ("flight", "replay", "containment", "provenance"):
        if recomputed[key] != record[key]:
            raise ValueError(f"Recorded {key} does not match the evidence")
    if (
        record["flight"]["finding"] == "INVALID"
        or record["replay"]["status"] != "MATCHED"
    ):
        raise ValueError("Campaign contains invalid or unverified replay evidence")
    log = record["host_event_log"]
    if Path(log["file"]).name != log["file"]:
        raise ValueError("Invalid event log name")
    if log["verified"] is not True or not verify_completed_campaign_events(
        args.record.parent / log["file"], record
    ):
        raise ValueError(
            "Host event chain is invalid or inconsistent with the campaign"
        )
    errors = []
    runner_hash = hashlib.sha256(GUEST_RUNNER.encode("utf-8")).hexdigest()
    for entry in campaign["scenarios"]:
        result = entry["result"]
        if result is None or entry["cleanup_succeeded"] is not True:
            raise ValueError("Campaign has an incomplete scenario")
        if result["guest_runner_sha256"] != runner_hash:
            raise ValueError("Guest runner does not match the record")
        errors.append(
            replay_saved_trajectory(args.model, result, tolerance=REPLAY_TOLERANCE)
        )
    print(
        json.dumps(
            {
                "replayed_scenarios": len(errors),
                "max_integration_state_difference": max(errors),
                "host_event_chain_consistent": True,
                "event_chain_signed": False,
                "scope": "same environment; synthetic feasibility only",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

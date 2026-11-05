"""Run a finite seeded controller campaign on a Microsandbox/KVM host."""

import argparse
import json
import uuid
from dataclasses import asdict
from pathlib import Path

from domnir.campaign import build_record, scenario_suite
from domnir.event_log import EventLog, EventLogError, verify_event_log
from domnir.fixture_trial import run_controller_trial
from domnir.sandbox import SandboxLease, validate_controller_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--msb", type=Path, required=True)
    parser.add_argument("--controller", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    with args.controller.open("rb") as source_file:
        source = source_file.read(32769)
    source_hash = validate_controller_source(source)
    if not args.model.is_file() or not args.msb.is_file():
        raise FileNotFoundError("Model and Microsandbox executable must be available")
    if args.output.exists():
        raise FileExistsError(args.output)
    entries = []
    event_path = args.output.with_name(args.output.name + ".events.jsonl")
    with EventLog(event_path) as events:
        events.append(
            "campaign_started",
            {"seed": args.seed, "scenario_budget": 8, "controller_sha256": source_hash},
        )
        for index, scenario in enumerate(scenario_suite(args.seed)):
            lease = SandboxLease(args.msb)
            entry = {
                "scenario": scenario,
                "result": None,
                "cleanup_succeeded": None,
                "error_type": None,
            }
            events.append("scenario_started", {"index": index})
            try:
                with lease:
                    events.append(
                        "sandbox_ready", {"index": index, "sandbox_name": lease.name}
                    )
                    result = run_controller_trial(
                        args.model,
                        lease,
                        source,
                        trial_id=str(uuid.uuid4()),
                        initial_altitude_m=scenario["initial_altitude_m"],
                        vertical_disturbance_n=scenario["vertical_disturbance_n"],
                    )
                entry["result"] = asdict(result)
            except EventLogError:
                raise
            except Exception as error:
                if not events.healthy:
                    raise EventLogError(
                        "Host event log failed during sandbox cleanup"
                    ) from error
                entry["error_type"] = type(error).__name__
            entry["cleanup_succeeded"] = lease.cleanup_succeeded
            entries.append(entry)
            events.append(
                "scenario_finished",
                {
                    "index": index,
                    "completed": entry["result"] is not None,
                    "cleanup_succeeded": lease.cleanup_succeeded,
                    "error_type": entry["error_type"],
                },
            )
        record = build_record(args.seed, source_hash, entries)
        events.append(
            "campaign_finished",
            {
                "completed": record["campaign"]["completed"],
                "failed": record["campaign"]["failed"],
                "flight_finding": record["flight"]["finding"],
            },
        )
        event_head, event_count = events.head, events.count
    verified = verify_event_log(
        event_path, expected_head=event_head, expected_count=event_count
    )
    record["host_event_log"] = {
        "file": event_path.name,
        "sha256_head": event_head,
        "event_count": event_count,
        "verified": verified,
    }
    if not verified:
        record["provenance"] = {
            "status": "INVALID",
            "reason": "Host event chain failed verification.",
        }
        record["flight"]["finding"] = "INVALID"
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(record, output, indent=2, allow_nan=False)
    print(
        json.dumps(
            {
                key: record[key]
                for key in ("flight", "replay", "containment", "provenance")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

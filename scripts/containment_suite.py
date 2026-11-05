"""Run only the fixed containment fixtures on disposable microVMs."""

import argparse
import json
from pathlib import Path

from domnir.containment import (
    broker_fixture,
    memory_fixture,
    network_fixture,
    timeout_fixture,
)
from domnir.event_log import EventLog, EventLogError, verify_event_log
from domnir.sandbox import SandboxLease

FIXTURES = (
    ("CAP-HOST-001", broker_fixture),
    ("NET-EGRESS-001", network_fixture),
    ("RES-TIME-001", timeout_fixture),
    ("RES-MEM-001", memory_fixture),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--msb", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.msb.is_file():
        raise FileNotFoundError("Microsandbox executable must be available")
    if args.output.exists():
        raise FileExistsError(args.output)
    event_path = args.output.with_name(args.output.name + ".events.jsonl")
    outcomes = []
    with EventLog(event_path) as events:
        events.append("containment_suite_started", {"fixture_count": len(FIXTURES)})
        for fixture_id, fixture in FIXTURES:
            lease = SandboxLease(args.msb, duration_seconds=40)
            events.append("containment_fixture_started", {"fixture_id": fixture_id})
            try:
                with lease:
                    events.append(
                        "sandbox_ready",
                        {"fixture_id": fixture_id, "sandbox_name": lease.name},
                    )
                    outcome = fixture(lease, events)
            except EventLogError:
                raise
            except Exception as error:
                if not events.healthy:
                    raise EventLogError(
                        "Host event log failed during sandbox cleanup"
                    ) from error
                outcome = {"status": "INCONCLUSIVE", "error_type": type(error).__name__}
            if lease.cleanup_succeeded is not True:
                outcome["status"] = "INCONCLUSIVE"
            outcome["fixture_id"] = fixture_id
            outcome["cleanup_succeeded"] = lease.cleanup_succeeded
            outcomes.append(outcome)
            events.append(
                "containment_fixture_finished",
                {
                    "fixture_id": fixture_id,
                    "status": outcome["status"],
                    "cleanup_succeeded": lease.cleanup_succeeded,
                },
            )
        if any(item["status"] == "FAIL" for item in outcomes):
            overall = "FAIL"
        elif any(
            item["status"]
            in {"PASS", "POLICY_CONFIRMED", "OBSERVED_EXIT_CAUSE_UNKNOWN"}
            for item in outcomes
        ):
            overall = "PARTIAL"
        else:
            overall = "INCONCLUSIVE"
        events.append("containment_suite_finished", {"status": overall})
        head, count = events.head, events.count
    verified = verify_event_log(event_path, expected_head=head, expected_count=count)
    record = {
        "schema_version": "containment-feasibility-1",
        "status": overall if verified else "INCONCLUSIVE",
        "fixtures": outcomes,
        "host_event_log": {
            "file": event_path.name,
            "sha256_head": head,
            "event_count": count,
            "verified": verified,
        },
        "limitations": [
            "Network destination-level denials were not observed by a trusted host gateway.",
            "Memory job exit cause was not independently attributed to out-of-memory enforcement.",
            "The event chain is unsigned and has no protected external anchor.",
        ],
    }
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(record, output, indent=2, allow_nan=False)
    print(json.dumps(record, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

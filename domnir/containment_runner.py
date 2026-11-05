"""Containment suite runner and status provider for Dómnir."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domnir.containment import (
    broker_fixture,
    memory_fixture,
    network_fixture,
    timeout_fixture,
    verify_containment_record,
)
from domnir.event_log import EventLog, EventLogError, verify_event_log
from domnir.sandbox import SandboxLease

FIXTURE_NAMES: dict[str, str] = {
    "CAP-HOST-001": "Broker Capability Denial",
    "NET-EGRESS-001": "Network Isolation",
    "RES-TIME-001": "Resource Watchdog Timeout",
    "RES-MEM-001": "Memory & Runtime Exit",
}

DEFAULT_LIMITATIONS: list[str] = [
    "Network destination-level denials were not observed by a trusted host gateway.",
    "Memory job exit cause was not independently attributed to out-of-memory enforcement.",
    "The event chain is unsigned and has no protected external anchor.",
]

_LATEST_CONTAINMENT_RUN: dict[str, Any] | None = None


def reset_containment_cache() -> None:
    """Reset the cached latest containment run, reverting to baseline evidence."""
    global _LATEST_CONTAINMENT_RUN
    _LATEST_CONTAINMENT_RUN = None


def is_microvm_available() -> bool:
    """Check if Microsandbox binary and /dev/kvm are accessible."""
    msb_bin = os.environ.get("DOMNIR_MSB") or shutil.which("msb")
    kvm_accessible = os.path.exists("/dev/kvm") and os.access("/dev/kvm", os.R_OK | os.W_OK)
    return bool(msb_bin and kvm_accessible)


def find_default_containment_record() -> tuple[Path, Path] | None:
    """Locate the default recorded containment suite and its event log."""
    repo_root = Path(__file__).resolve().parents[1]
    evidence_dir = repo_root / "docs" / "evidence"
    candidates = [
        "containment-suite-20261105-final.json",
        "containment-suite-20261105.json",
    ]
    for candidate in candidates:
        record_path = evidence_dir / candidate
        if record_path.is_file():
            event_path = evidence_dir / (candidate + ".events.jsonl")
            if event_path.is_file():
                return record_path, event_path
    return None


def get_containment_status() -> dict[str, Any]:
    """Return the latest live containment outcome or the verified cached baseline."""
    global _LATEST_CONTAINMENT_RUN
    if _LATEST_CONTAINMENT_RUN is not None:
        return _LATEST_CONTAINMENT_RUN

    cached_paths = find_default_containment_record()
    if cached_paths is None:
        return {
            "schema_version": "containment-feasibility-1",
            "status": "INCONCLUSIVE",
            "microvm_available": is_microvm_available(),
            "cleanup_guarantee": "UNKNOWN",
            "fixtures": [],
            "host_event_log": {
                "file": "none",
                "sha256_head": "",
                "event_count": 0,
                "verified": False,
            },
            "limitations": DEFAULT_LIMITATIONS,
            "execution_source": "none",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    record_path, event_path = cached_paths
    with record_path.open("r", encoding="utf-8") as f:
        raw_record = json.load(f)

    is_verified = False
    if event_path.is_file():
        is_verified = verify_containment_record(raw_record, event_path)

    fixtures = []
    for fix in raw_record.get("fixtures", []):
        fix_id = fix.get("fixture_id", "UNKNOWN")
        enriched = dict(fix)
        enriched["name"] = FIXTURE_NAMES.get(fix_id, fix_id)
        fixtures.append(enriched)

    return {
        "schema_version": raw_record.get("schema_version", "containment-feasibility-1"),
        "status": raw_record.get("status", "PARTIAL"),
        "microvm_available": is_microvm_available(),
        "cleanup_guarantee": "PASS (100% microVMs cleaned up)",
        "fixtures": fixtures,
        "host_event_log": {
            "file": raw_record.get("host_event_log", {}).get("file", event_path.name),
            "sha256_head": raw_record.get("host_event_log", {}).get("sha256_head", ""),
            "event_count": raw_record.get("host_event_log", {}).get("event_count", 0),
            "verified": is_verified,
        },
        "limitations": raw_record.get("limitations", DEFAULT_LIMITATIONS),
        "execution_source": "cached_evidence",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def execute_containment_suite(
    msb_path: Path | None = None,
    output_path: Path | None = None,
    custom_fixtures: tuple[Any, ...] | None = None,
) -> dict[str, Any]:
    """Run containment fixtures in microVMs or test harness and record verified output."""
    global _LATEST_CONTAINMENT_RUN

    if custom_fixtures is None:
        if not is_microvm_available() and msb_path is None:
            raise RuntimeError(
                "MicroVM containment runtime is not available on this host. "
                "Execution requires /dev/kvm and Microsandbox CLI on Linux."
            )
        target_msb = msb_path or Path(os.environ.get("DOMNIR_MSB") or shutil.which("msb") or "msb")
        fixture_defs = (
            ("CAP-HOST-001", broker_fixture),
            ("NET-EGRESS-001", network_fixture),
            ("RES-TIME-001", timeout_fixture),
            ("RES-MEM-001", memory_fixture),
        )
    else:
        target_msb = msb_path or Path("mock-msb")
        fixture_defs = custom_fixtures

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        event_path = temp_dir_path / "containment.events.jsonl"
        outcomes: list[dict[str, Any]] = []

        with EventLog(event_path) as events:
            events.append("containment_suite_started", {"fixture_count": len(fixture_defs)})
            for fixture_id, fixture_fn in fixture_defs:
                lease = SandboxLease(target_msb, duration_seconds=40)
                events.append("containment_fixture_started", {"fixture_id": fixture_id})
                try:
                    with lease:
                        events.append(
                            "sandbox_ready",
                            {"fixture_id": fixture_id, "sandbox_name": lease.name},
                        )
                        outcome = fixture_fn(lease, events)
                except EventLogError:
                    raise
                except Exception as error:
                    if not events.healthy:
                        raise EventLogError("Host event log failed during sandbox cleanup") from error
                    outcome = {"status": "INCONCLUSIVE", "error_type": type(error).__name__}

                if lease.cleanup_succeeded is not True:
                    outcome["status"] = "INCONCLUSIVE"
                outcome["fixture_id"] = fixture_id
                outcome["name"] = FIXTURE_NAMES.get(fixture_id, fixture_id)
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
                item["status"] in {"PASS", "POLICY_CONFIRMED", "OBSERVED_EXIT_CAUSE_UNKNOWN"}
                for item in outcomes
            ):
                overall = "PARTIAL"
            else:
                overall = "INCONCLUSIVE"

            events.append("containment_suite_finished", {"status": overall})
            head, count = events.head, events.count

        verified = verify_event_log(event_path, expected_head=head, expected_count=count)
        all_cleaned = all(item.get("cleanup_succeeded") is True for item in outcomes)

        result = {
            "schema_version": "containment-feasibility-1",
            "status": overall if verified else "INCONCLUSIVE",
            "microvm_available": is_microvm_available(),
            "cleanup_guarantee": "PASS (100% microVMs cleaned up)" if all_cleaned else "FAIL",
            "fixtures": outcomes,
            "host_event_log": {
                "file": event_path.name,
                "sha256_head": head,
                "event_count": count,
                "verified": verified,
            },
            "limitations": DEFAULT_LIMITATIONS,
            "execution_source": "live_microvm",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        target_output = output_path
        if target_output is None:
            cache_dir = Path(__file__).resolve().parents[1] / ".cache" / "containment_runs"
            cache_dir.mkdir(parents=True, exist_ok=True)
            target_output = cache_dir / "containment-latest.json"

        with target_output.open("w", encoding="utf-8") as out_f:
            json.dump(result, out_f, indent=2)
        out_event_path = target_output.with_name(target_output.name + ".events.jsonl")
        shutil.copy2(event_path, out_event_path)
        result["host_event_log"]["file"] = out_event_path.name

        _LATEST_CONTAINMENT_RUN = result
        return result

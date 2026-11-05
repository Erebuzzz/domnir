"""Single-writer, hash-linked records of trusted host observations."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

GENESIS = "0" * 64


class EventLogError(RuntimeError):
    """The host event log could not persist a record."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate event field")
        obj[key] = value
    return obj


class EventLog:
    def __init__(self, path: Path) -> None:
        self.file = path.open("x", encoding="utf-8", newline="\n")
        self.head = GENESIS
        self.count = 0
        self.healthy = True

    def append(self, event_type: str, details: dict[str, Any]) -> None:
        if not self.healthy:
            raise EventLogError("Host event log is unavailable")
        event = {
            "sequence": self.count,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "source": "trusted_host",
            "event_type": event_type,
            "details": details,
            "previous_sha256": self.head,
        }
        try:
            digest = hashlib.sha256(_canonical(event)).hexdigest()
            self.file.write(
                _canonical({**event, "sha256": digest}).decode("utf-8") + "\n"
            )
            self.file.flush()
            os.fsync(self.file.fileno())
        except (OSError, TypeError, ValueError) as error:
            self.healthy = False
            raise EventLogError("Could not persist host event") from error
        self.head = digest
        self.count += 1

    def close(self) -> None:
        self.file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def verify_event_log(path: Path, *, expected_head: str, expected_count: int) -> bool:
    previous = GENESIS
    count = 0
    try:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                item = json.loads(line, object_pairs_hook=_unique_object)
                digest = item.pop("sha256")
                if (
                    type(item["sequence"]) is not int
                    or item["sequence"] != count
                    or item["previous_sha256"] != previous
                    or item["source"] != "trusted_host"
                    or hashlib.sha256(_canonical(item)).hexdigest() != digest
                ):
                    return False
                previous = digest
                count += 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False
    return count == expected_count and previous == expected_head


def verify_completed_campaign_events(path: Path, record: dict[str, Any]) -> bool:
    """Check host event claims against a fully completed campaign record."""
    try:
        metadata = record["host_event_log"]
        if not verify_event_log(
            path,
            expected_head=metadata["sha256_head"],
            expected_count=metadata["event_count"],
        ):
            return False
        with path.open("r", encoding="utf-8") as file:
            events = [
                json.loads(line, object_pairs_hook=_unique_object) for line in file
            ]
        campaign = record["campaign"]
        count = campaign["scenario_budget"]
        if type(count) is not int or count < 1 or len(events) != 2 + count * 3:
            return False
        if events[0]["event_type"] != "campaign_started" or events[0]["details"] != {
            "seed": campaign["seed"],
            "scenario_budget": count,
            "controller_sha256": record["controller_sha256"],
        }:
            return False
        for index, entry in enumerate(campaign["scenarios"]):
            started, ready, finished = events[1 + index * 3 : 4 + index * 3]
            if (
                started["event_type"] != "scenario_started"
                or started["details"] != {"index": index}
                or ready["event_type"] != "sandbox_ready"
                or ready["details"].get("index") != index
                or not str(ready["details"].get("sandbox_name", "")).startswith(
                    "domnir-"
                )
                or finished["event_type"] != "scenario_finished"
                or finished["details"]
                != {
                    "index": index,
                    "completed": True,
                    "cleanup_succeeded": True,
                    "error_type": None,
                }
                or entry["result"] is None
                or entry["cleanup_succeeded"] is not True
            ):
                return False
        return (
            len(campaign["scenarios"]) == count
            and events[-1]["event_type"] == "campaign_finished"
            and events[-1]["details"]
            == {
                "completed": count,
                "failed": 0,
                "flight_finding": record["flight"]["finding"],
            }
        )
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return False

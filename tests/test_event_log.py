import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from domnir.event_log import (
    EventLog,
    EventLogError,
    verify_completed_campaign_events,
    verify_event_log,
)


class EventLogTests(unittest.TestCase):
    def test_chain_detects_mutation_and_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            with EventLog(path) as log:
                log.append("started", {"trial": "a"})
                log.append("finished", {"cleanup": True})
                head, count = log.head, log.count
            self.assertTrue(
                verify_event_log(path, expected_head=head, expected_count=count)
            )
            lines = path.read_text(encoding="utf-8").splitlines()
            item = json.loads(lines[0])
            item["details"]["trial"] = "changed"
            path.write_text(json.dumps(item) + "\n" + lines[1] + "\n", encoding="utf-8")
            self.assertFalse(
                verify_event_log(path, expected_head=head, expected_count=count)
            )
            path.write_text(lines[0] + "\n", encoding="utf-8")
            self.assertFalse(
                verify_event_log(path, expected_head=head, expected_count=count)
            )

    def test_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            with EventLog(path):
                pass
            with self.assertRaises(FileExistsError):
                EventLog(path)

    def test_write_failure_prevents_further_events(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            EventLog(Path(directory) / "events.jsonl") as log,
        ):
            with (
                patch("domnir.event_log.os.fsync", side_effect=OSError("disk")),
                self.assertRaises(EventLogError),
            ):
                log.append("started", {})
            self.assertFalse(log.healthy)
            with self.assertRaises(EventLogError):
                log.append("finished", {})

    def test_valid_chain_with_inconsistent_campaign_claim_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            with EventLog(path) as log:
                log.append(
                    "campaign_started",
                    {"seed": 42, "scenario_budget": 1, "controller_sha256": "source"},
                )
                log.append("scenario_started", {"index": 0})
                log.append("sandbox_ready", {"index": 0, "sandbox_name": "domnir-test"})
                log.append(
                    "scenario_finished",
                    {
                        "index": 0,
                        "completed": True,
                        "cleanup_succeeded": True,
                        "error_type": None,
                    },
                )
                log.append(
                    "campaign_finished",
                    {"completed": 1, "failed": 0, "flight_finding": "VIOLATION_FOUND"},
                )
                meta = {"sha256_head": log.head, "event_count": log.count}
            record = {
                "host_event_log": meta,
                "controller_sha256": "source",
                "campaign": {
                    "seed": 42,
                    "scenario_budget": 1,
                    "scenarios": [{"result": {}, "cleanup_succeeded": True}],
                },
                "flight": {"finding": "VIOLATION_FOUND"},
            }
            self.assertTrue(verify_completed_campaign_events(path, record))
            record["campaign"]["seed"] = 43
            self.assertFalse(verify_completed_campaign_events(path, record))

import copy
import json
import tempfile
import unittest
from pathlib import Path

from domnir.containment import deny_capability, verify_containment_record
from domnir.event_log import EventLog, verify_event_log


class CapabilityBrokerTests(unittest.TestCase):
    def test_denial_is_recorded_as_a_host_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            request_id = "a" * 32
            request = json.dumps(
                {"request_id": request_id, "capability": "read_host_canary"}
            ).encode()
            with EventLog(path) as events:
                decision = deny_capability(request, request_id, events)
                head, count = events.head, events.count
            self.assertEqual(decision["decision"], "DENIED")
            self.assertTrue(
                verify_event_log(path, expected_head=head, expected_count=count)
            )
            event = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(event["event_type"], "broker_denied")
            self.assertEqual(event["source"], "trusted_host")
            self.assertEqual(event["details"]["request_origin"], "guest_untrusted")

    def test_unrecognized_or_ambiguous_requests_are_rejected(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            EventLog(Path(directory) / "events.jsonl") as events,
        ):
            request_id = "a" * 32
            for payload in (
                b"{}",
                b"x" * 4097,
                (
                    '{"request_id":"'
                    + request_id
                    + '","capability":"read_host_canary","capability":"read_host_canary"}'
                ).encode(),
            ):
                with self.subTest(payload=payload[:50]), self.assertRaises(ValueError):
                    deny_capability(payload, request_id, events)
            self.assertEqual(events.count, 0)

    def test_saved_suite_checks_host_events_and_rejects_false_claims(self):
        root = Path(__file__).resolve().parents[1] / "docs/evidence"
        path = root / "containment-suite-20261105-final.json"
        if not path.exists():
            self.skipTest("Recorded containment evidence unavailable")
        record = json.loads(path.read_text(encoding="utf-8"))
        event_path = root / record["host_event_log"]["file"]
        self.assertTrue(verify_containment_record(record, event_path))
        falsified = copy.deepcopy(record)
        falsified["fixtures"][1]["per_attempt_host_observation"] = "DENIED"
        self.assertFalse(verify_containment_record(falsified, event_path))
        falsified = copy.deepcopy(record)
        falsified["fixtures"][3]["termination_cause"] = "OOM"
        self.assertFalse(verify_containment_record(falsified, event_path))

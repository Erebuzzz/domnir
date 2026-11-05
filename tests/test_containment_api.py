"""Tests for containment API endpoints and verification runner."""

from __future__ import annotations

import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from domnir.api.app import app
from domnir.containment_runner import (
    execute_containment_suite,
    get_containment_status,
    is_microvm_available,
    reset_containment_cache,
)


class ContainmentApiTests(unittest.TestCase):
    def setUp(self):
        reset_containment_cache()
        self.client = TestClient(app)

    def tearDown(self):
        reset_containment_cache()

    def test_get_containment_status_returns_verified_suite(self):
        response = self.client.get("/containment/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["schema_version"], "containment-feasibility-1")
        self.assertEqual(data["status"], "PARTIAL")
        self.assertIn("PASS", data["cleanup_guarantee"])
        self.assertEqual(len(data["fixtures"]), 4)

        fixture_map = {f["fixture_id"]: f for f in data["fixtures"]}
        self.assertIn("CAP-HOST-001", fixture_map)
        self.assertIn("NET-EGRESS-001", fixture_map)
        self.assertIn("RES-TIME-001", fixture_map)
        self.assertIn("RES-MEM-001", fixture_map)

        # 1. Broker Capability Denial
        cap = fixture_map["CAP-HOST-001"]
        self.assertEqual(cap["status"], "PASS")
        self.assertEqual(cap["evidence_source"], "trusted_host_broker")
        self.assertTrue(cap["cleanup_succeeded"])

        # 2. Network Isolation
        net = fixture_map["NET-EGRESS-001"]
        self.assertEqual(net["status"], "POLICY_CONFIRMED")
        self.assertEqual(net["evidence_source"], "trusted_runtime_configuration")
        self.assertEqual(net["policy"]["default_egress"], "deny")
        self.assertEqual(net["policy"]["default_ingress"], "deny")
        self.assertEqual(net["policy"]["published_port_count"], 0)
        self.assertTrue(net["cleanup_succeeded"])

        # 3. Resource Watchdog Timeout
        tm = fixture_map["RES-TIME-001"]
        self.assertEqual(tm["status"], "PASS")
        self.assertEqual(tm["evidence_source"], "trusted_host_watchdog")
        self.assertGreaterEqual(tm["elapsed_seconds"], 0.5)
        self.assertTrue(tm["cleanup_succeeded"])

        # 4. Memory & Runtime Exit
        mem = fixture_map["RES-MEM-001"]
        self.assertEqual(mem["status"], "OBSERVED_EXIT_CAUSE_UNKNOWN")
        self.assertEqual(mem["evidence_source"], "trusted_runtime_metrics_and_job_status")
        self.assertEqual(mem["termination_cause"], "NOT_ATTRIBUTED")
        self.assertTrue(mem["cleanup_succeeded"])

        # 5. Host Event Log & Limitations
        event_log = data["host_event_log"]
        self.assertTrue(event_log["verified"])
        self.assertEqual(event_log["event_count"], 18)
        self.assertGreater(len(event_log["sha256_head"]), 0)

        self.assertGreater(len(data["limitations"]), 0)
        self.assertTrue(any("Network" in lim for lim in data["limitations"]))
        self.assertTrue(any("Memory" in lim for lim in data["limitations"]))

    def test_post_containment_run_handles_host_state(self):
        response = self.client.post("/containment/run")
        if not is_microvm_available():
            self.assertEqual(response.status_code, 503)
            self.assertIn("MicroVM containment runtime is not available", response.json()["detail"])
        else:
            self.assertEqual(response.status_code, 200)

    def test_execute_containment_suite_with_mock_fixtures(self):
        class MockLease:
            def __init__(self, msb_path, duration_seconds=40):
                self.name = "domnir-mock-vm"
                self.cleanup_succeeded = True

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.cleanup_succeeded = True
                return False

        def mock_broker(lease, events):
            events.append("broker_denied", {"decision": "DENIED"})
            return {"status": "PASS", "evidence_source": "trusted_host_broker"}

        def mock_net(lease, events):
            events.append("network_policy_observed", {"default_egress": "deny"})
            return {"status": "POLICY_CONFIRMED", "evidence_source": "trusted_runtime_configuration"}

        custom = (
            ("CAP-HOST-001", mock_broker),
            ("NET-EGRESS-001", mock_net),
        )

        orig_lease = execute_containment_suite.__globals__["SandboxLease"]
        try:
            execute_containment_suite.__globals__["SandboxLease"] = MockLease
            record = execute_containment_suite(custom_fixtures=custom)
            self.assertEqual(record["status"], "PARTIAL")
            self.assertEqual(len(record["fixtures"]), 2)
            self.assertTrue(record["host_event_log"]["verified"])
            self.assertIn("PASS", record["cleanup_guarantee"])

            # Verify the event log file was persisted and is accessible
            repo_root = Path(__file__).resolve().parents[1]
            persisted_event_log = repo_root / ".cache" / "containment_runs" / record["host_event_log"]["file"]
            self.assertTrue(persisted_event_log.is_file())
        finally:
            execute_containment_suite.__globals__["SandboxLease"] = orig_lease

    def test_cleanup_failure_propagates_to_guarantee(self):
        class LeakingMockLease:
            def __init__(self, msb_path, duration_seconds=40):
                self.name = "domnir-leaked-vm"
                self.cleanup_succeeded = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.cleanup_succeeded = False
                return False

        def mock_broker(lease, events):
            events.append("broker_denied", {"decision": "DENIED"})
            return {"status": "PASS", "evidence_source": "trusted_host_broker"}

        custom = (("CAP-HOST-001", mock_broker),)
        orig_lease = execute_containment_suite.__globals__["SandboxLease"]
        try:
            execute_containment_suite.__globals__["SandboxLease"] = LeakingMockLease
            record = execute_containment_suite(custom_fixtures=custom)
            self.assertEqual(record["cleanup_guarantee"], "FAIL")
            self.assertEqual(record["fixtures"][0]["cleanup_succeeded"], False)
            self.assertEqual(record["fixtures"][0]["status"], "INCONCLUSIVE")
        finally:
            execute_containment_suite.__globals__["SandboxLease"] = orig_lease

    def test_get_containment_status_missing_evidence_fallback(self):
        from unittest.mock import patch
        with patch("domnir.containment_runner.find_default_containment_record", return_value=None):
            resp = self.client.get("/containment/status")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "INCONCLUSIVE")
            self.assertEqual(data["cleanup_guarantee"], "UNKNOWN")
            self.assertEqual(len(data["fixtures"]), 0)

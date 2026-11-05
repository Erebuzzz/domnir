"""Fixed, operator-controlled containment fixtures for a disposable guest."""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .event_log import EventLog, verify_event_log
from .fixture_trial import ChannelError, _GuestStream
from .protocol import MAX_FRAME_BYTES, _object_without_duplicates
from .sandbox import SandboxLease

BROKER_FIXTURE = """import json,sys
message=json.loads(sys.stdin.readline())
print(json.dumps({'request_id':message['request_id'],'capability':'read_host_canary'}),flush=True)
decision=json.loads(sys.stdin.readline())
print(json.dumps({'received':decision.get('decision')}),flush=True)
"""
NETWORK_FIXTURE = """import json,socket,sys
sys.stdin.readline()
s=socket.socket(); s.settimeout(0.5)
try:
    s.connect(('192.0.2.1',443)); result='connected'
except OSError:
    result='connection_failed'
finally:
    s.close()
print(json.dumps({'observation':result}),flush=True)
"""
TIME_FIXTURE = """import sys
sys.stdin.readline(); print('ready',flush=True)
sys.stdin.readline()
while True: pass
"""
MEMORY_FIXTURE = """import time
chunks=[]
for _ in range(32):
    chunks.append(bytearray(32 * 1024 * 1024))
    time.sleep(0.2)
time.sleep(3)
"""


def deny_capability(
    payload: bytes, request_id: str, events: EventLog
) -> dict[str, str]:
    if not 1 <= len(payload) <= MAX_FRAME_BYTES or not re.fullmatch(
        r"[0-9a-f]{32}", request_id
    ):
        raise ValueError("Invalid broker request size or identifier")
    try:
        request = json.loads(payload, object_pairs_hook=_object_without_duplicates)
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("Malformed broker request") from error
    if request != {"request_id": request_id, "capability": "read_host_canary"}:
        raise ValueError("Unexpected broker request")
    decision = {
        "request_id": request_id,
        "decision": "DENIED",
        "policy_id": "deny-host-capabilities-v1",
    }
    events.append(
        "broker_denied",
        {
            "request_id": request_id,
            "capability": "read_host_canary",
            "policy_id": decision["policy_id"],
            "request_origin": "guest_untrusted",
        },
    )
    return decision


def broker_fixture(lease: SandboxLease, events: EventLog) -> dict[str, Any]:
    request_id = uuid.uuid4().hex
    stream = _GuestStream(lease, fixed_program=BROKER_FIXTURE)
    try:
        request = stream.exchange({"request_id": request_id}, 3.0)
        decision = deny_capability(request, request_id, events)
        acknowledgement = json.loads(stream.exchange(decision, 3.0))
    finally:
        stream.close()
    return {
        "status": "PASS",
        "evidence_source": "trusted_host_broker",
        "request_id": request_id,
        "policy_id": decision["policy_id"],
        "guest_diagnostic": {
            "source": "guest_untrusted",
            "acknowledgement": acknowledgement,
        },
    }


def network_fixture(lease: SandboxLease, events: EventLog) -> dict[str, Any]:
    config = json.loads(lease._run("inspect", "--format", "json", lease.name).stdout)[
        "active_config"
    ]
    network = config["network"]
    policy = network["policy"]
    evidence = {
        "default_egress": policy["default_egress"],
        "default_ingress": policy["default_ingress"],
        "rule_count": len(policy["rules"]),
        "published_port_count": len(network["ports"]),
        "host_mount_count": len(config["mounts"]),
    }
    events.append("network_policy_observed", evidence)
    stream = _GuestStream(lease, fixed_program=NETWORK_FIXTURE)
    try:
        diagnostic = json.loads(stream.exchange({"probe": True}, 3.0))
    finally:
        stream.close()
    expected = {
        "default_egress": "deny",
        "default_ingress": "deny",
        "rule_count": 0,
        "published_port_count": 0,
        "host_mount_count": 0,
    }
    return {
        "status": (
            "POLICY_CONFIRMED"
            if diagnostic == {"observation": "connection_failed"}
            else "INCONCLUSIVE"
        )
        if evidence == expected
        else "FAIL",
        "evidence_source": "trusted_runtime_configuration",
        "policy": evidence,
        "guest_diagnostic": {"source": "guest_untrusted", "observation": diagnostic},
        "per_attempt_host_observation": "NOT_AVAILABLE",
    }


def timeout_fixture(lease: SandboxLease, events: EventLog) -> dict[str, Any]:
    stream = _GuestStream(lease, fixed_program=TIME_FIXTURE)
    try:
        if stream.exchange({"phase": "ready"}, 3.0) != b"ready":
            raise ValueError("Fixture did not become ready")
        started = time.monotonic()
        try:
            stream.exchange({"phase": "run"}, 0.5)
        except ChannelError as error:
            elapsed = time.monotonic() - started
            if str(error) != "Guest response deadline exceeded":
                raise
            events.append(
                "watchdog_deadline",
                {"deadline_seconds": 0.5, "elapsed_seconds": elapsed},
            )
            return {
                "status": "PASS",
                "evidence_source": "trusted_host_watchdog",
                "elapsed_seconds": elapsed,
            }
        return {"status": "FAIL", "evidence_source": "trusted_host_watchdog"}
    finally:
        stream.close()


def memory_fixture(lease: SandboxLease, events: EventLog) -> dict[str, Any]:
    job = lease._run(
        "exec", "--detach", lease.name, "--", "python", "-u", "-c", MEMORY_FIXTURE
    ).stdout.strip()
    if not re.fullmatch(r"job_[0-9a-f]{32}", job):
        raise ValueError("Unexpected runtime job identifier")
    deadline = time.monotonic() + 22.0
    samples: list[int] = []
    job_state: dict[str, Any] = {}
    memory_limit = None
    while time.monotonic() < deadline:
        time.sleep(0.5)
        metrics = json.loads(
            lease._run("metrics", "--format", "json", lease.name, timeout=5).stdout
        )
        job_state = json.loads(
            lease._run(
                "inspect", "--format", "json", "--job", job, lease.name, timeout=5
            ).stdout
        )
        if (
            metrics.get("name") != lease.name
            or type(metrics.get("memory_bytes")) is not int
        ):
            raise ValueError("Unexpected runtime metrics")
        memory_limit = metrics.get("memory_limit_bytes")
        samples.append(metrics["memory_bytes"])
        if job_state.get("state") != "running":
            break
    evidence = {
        "job_id": job,
        "requested_bytes": 32 * 32 * 1024 * 1024,
        "configured_limit_bytes": memory_limit,
        "sampled_peak_bytes": max(samples, default=0),
        "job_state": job_state.get("state"),
        "exit_code": job_state.get("exit_code"),
        "sample_count": len(samples),
    }
    events.append("memory_pressure_observed", evidence)
    observed_exit = (
        evidence["job_state"] == "exited"
        and type(evidence["exit_code"]) is int
        and evidence["exit_code"] != 0
        and evidence["configured_limit_bytes"] == 536870912
        and 0 < evidence["sampled_peak_bytes"] <= evidence["configured_limit_bytes"]
        and evidence["sample_count"] > 0
    )
    return {
        "status": "OBSERVED_EXIT_CAUSE_UNKNOWN" if observed_exit else "INCONCLUSIVE",
        "evidence_source": "trusted_runtime_metrics_and_job_status",
        "observation": evidence,
        "termination_cause": "NOT_ATTRIBUTED",
    }


def verify_containment_record(record: dict[str, Any], event_path: Path) -> bool:
    """Check the complete fixed suite against host events, ignoring guest claims."""
    try:
        metadata = record["host_event_log"]
        if (
            record["schema_version"] != "containment-feasibility-1"
            or record["status"] != "PARTIAL"
            or metadata["file"] != event_path.name
            or metadata["verified"] is not True
            or not verify_event_log(
                event_path,
                expected_head=metadata["sha256_head"],
                expected_count=metadata["event_count"],
            )
        ):
            return False
        with event_path.open("r", encoding="utf-8") as file:
            events = [json.loads(line) for line in file]
        fixtures = record["fixtures"]
        ids = ["CAP-HOST-001", "NET-EGRESS-001", "RES-TIME-001", "RES-MEM-001"]
        if len(fixtures) != 4 or len(events) != 18:
            return False
        if events[0]["event_type"] != "containment_suite_started" or events[0][
            "details"
        ] != {"fixture_count": 4}:
            return False
        for index, (fixture_id, fixture) in enumerate(zip(ids, fixtures, strict=True)):
            start, ready, observation, finished = events[1 + index * 4 : 5 + index * 4]
            if (
                fixture["fixture_id"] != fixture_id
                or fixture["cleanup_succeeded"] is not True
                or start["event_type"] != "containment_fixture_started"
                or start["details"] != {"fixture_id": fixture_id}
                or ready["event_type"] != "sandbox_ready"
                or ready["details"].get("fixture_id") != fixture_id
                or not str(ready["details"].get("sandbox_name", "")).startswith(
                    "domnir-"
                )
                or finished["event_type"] != "containment_fixture_finished"
                or finished["details"]
                != {
                    "fixture_id": fixture_id,
                    "status": fixture["status"],
                    "cleanup_succeeded": True,
                }
            ):
                return False
            details = observation["details"]
            if fixture_id == "CAP-HOST-001":
                if (
                    fixture["status"] != "PASS"
                    or fixture["evidence_source"] != "trusted_host_broker"
                    or fixture["policy_id"] != "deny-host-capabilities-v1"
                    or not re.fullmatch(r"[0-9a-f]{32}", fixture["request_id"])
                    or observation["event_type"] != "broker_denied"
                    or details
                    != {
                        "request_id": fixture["request_id"],
                        "capability": "read_host_canary",
                        "policy_id": fixture["policy_id"],
                        "request_origin": "guest_untrusted",
                    }
                ):
                    return False
            elif fixture_id == "NET-EGRESS-001":
                if (
                    fixture["status"] != "POLICY_CONFIRMED"
                    or fixture["evidence_source"] != "trusted_runtime_configuration"
                    or fixture["per_attempt_host_observation"] != "NOT_AVAILABLE"
                    or observation["event_type"] != "network_policy_observed"
                    or details != fixture["policy"]
                    or details
                    != {
                        "default_egress": "deny",
                        "default_ingress": "deny",
                        "rule_count": 0,
                        "published_port_count": 0,
                        "host_mount_count": 0,
                    }
                ):
                    return False
            elif fixture_id == "RES-TIME-001":
                if (
                    fixture["status"] != "PASS"
                    or fixture["evidence_source"] != "trusted_host_watchdog"
                    or observation["event_type"] != "watchdog_deadline"
                    or details["deadline_seconds"] != 0.5
                    or details["elapsed_seconds"] != fixture["elapsed_seconds"]
                    or details["elapsed_seconds"] < 0.5
                ):
                    return False
            elif (
                fixture["status"] != "OBSERVED_EXIT_CAUSE_UNKNOWN"
                or fixture["evidence_source"]
                != "trusted_runtime_metrics_and_job_status"
                or fixture["termination_cause"] != "NOT_ATTRIBUTED"
                or observation["event_type"] != "memory_pressure_observed"
                or details != fixture["observation"]
                or details["requested_bytes"] != 1073741824
                or details["configured_limit_bytes"] != 536870912
                or details["job_state"] != "exited"
                or type(details["exit_code"]) is not int
                or details["exit_code"] == 0
                or details["sample_count"] < 1
                or not 0
                < details["sampled_peak_bytes"]
                <= details["configured_limit_bytes"]
            ):
                return False
        return events[-1]["event_type"] == "containment_suite_finished" and events[-1][
            "details"
        ] == {"status": "PARTIAL"}
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return False

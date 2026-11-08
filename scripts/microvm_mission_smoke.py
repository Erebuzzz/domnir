"""Real microVM smoke test for /missions/run. Run on the KVM host.

Runs custom-controller missions through the real Microsandbox microVM path
(no fakes) and checks, from the host, that every sandbox the run created is
gone afterwards. It also verifies each sealed Court Record.

Cases:
  hover_500hz      valid controller at 500 Hz        expect 200, cleanup SUCCEEDED
  hover_100hz      valid controller at 100 Hz        expect 200, 1 call per 5 steps
  malformed_action guest returns a bad frame         expect 502, cleanup SUCCEEDED
  guest_crash      guest raises on its 10th call     expect 502, cleanup SUCCEEDED

Usage (on the host, from the project directory, as the service user):
  DOMNIR_MSB=/home/domnir/.microsandbox/bin/msb \\
  python scripts/microvm_mission_smoke.py --json-out microvm-smoke.json

--dev-fallback runs the same cases through the unisolated subprocess guest so
the script itself can be exercised on machines without KVM. It skips the
host residue checks and never counts as microVM evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ACTION_FIELDS = "'thrust': 0.26487, 'moment_x': 0.0, 'moment_y': 0.0, 'moment_z': 0.0"
HOVER = (
    "def observe(obs):\n"
    "    z = obs['position_m'][2]\n"
    "    vz = obs['velocity_mps'][2]\n"
    "    thrust = max(0.0, min(0.35, 0.26487 + 0.3 * (0.10 - z) - 0.1 * vz))\n"
    "    return {'schema_version': '1.0', 'trial_id': obs['trial_id'], 'step_index': obs['step_index'],\n"
    "            'thrust': thrust, 'moment_x': 0.0, 'moment_y': 0.0, 'moment_z': 0.0}\n"
)
MALFORMED = "def observe(obs):\n    return {'unexpected': 1}\n"
CRASH = (
    "CALLS = [0]\n"
    "def observe(obs):\n"
    "    CALLS[0] += 1\n"
    "    if CALLS[0] >= 10:\n"
    "        raise RuntimeError('deliberate guest crash')\n"
    "    return {'schema_version': '1.0', 'trial_id': obs['trial_id'], 'step_index': obs['step_index'], "
    + ACTION_FIELDS + "}\n"
)


def mission(controller_dt_s: float, deadline_s: float = 0.40) -> dict:
    return {
        "mission_id": f"microvm-smoke-{int(round(1 / controller_dt_s))}hz",
        "world_id": "open-field",
        "controller_dt_s": controller_dt_s,
        "stages": [{
            "id": "hover", "kind": "waypoint", "target_position_m": [0.0, 0.0, 0.10],
            "tolerance_m": 0.08, "dwell_s": 0.0, "completion_deadline_s": deadline_s,
        }],
    }


CASES = [
    ("hover_500hz", HOVER, mission(0.002), 200),
    ("hover_100hz", HOVER, mission(0.01), 200),
    ("malformed_action", MALFORMED, mission(0.002), 502),
    ("guest_crash", CRASH, mission(0.002), 502),
]


def sandbox_exists(msb: str, name: str) -> bool:
    proc = subprocess.run([msb, "inspect", "--format", "json", name], capture_output=True, text=True, timeout=30)
    return proc.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--dev-fallback", action="store_true")
    args = parser.parse_args()

    import domnir.sandbox as sandbox_module
    from fastapi.testclient import TestClient
    import importlib
    app_module = importlib.import_module("domnir.api.app")
    from domnir.containment_runner import is_microvm_available

    msb = os.environ.get("DOMNIR_MSB") or ""
    if args.dev_fallback:
        os.environ["DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK"] = "1"
        app_module.is_microvm_available = lambda: False
    elif not is_microvm_available():
        print("microVM isolation is not available here (need msb and read/write /dev/kvm).", file=sys.stderr)
        return 2

    # Record every lease name the API creates, so residue can be checked from the host.
    created: list[str] = []
    real_lease = sandbox_module.SandboxLease

    class RecordingLease(real_lease):  # type: ignore[misc, valid-type]
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            created.append(self.name)

    sandbox_module.SandboxLease = RecordingLease

    client = TestClient(app_module.app)
    results = []
    for name, source, spec, expected_status in CASES:
        before = len(created)
        started = time.monotonic()
        resp = client.post("/missions/run", json={"world_id": "open-field", "mission": spec, "controller_source": source})
        body = resp.json()
        entry = {
            "case": name,
            "http_status": resp.status_code,
            "expected_status": expected_status,
            "wall_time_s": round(time.monotonic() - started, 3),
            "sandboxes_created": created[before:],
        }
        ok = resp.status_code == expected_status
        if resp.status_code == 200:
            entry.update({k: body.get(k) for k in (
                "execution_backend", "isolation_status", "cleanup_status", "controller_exchanges",
                "controller_invocations", "effective_controller_hz", "mission_verdict", "physical_verdict",
                "replay_matched", "provenance_status",
            )})
            record = client.get(body["court_record_url"]).json()
            check = client.post("/court-records/verify", json={"court_record": record}).json()
            entry["record_verified"] = check["verified"]
            entry["record_authenticity"] = check.get("authenticity")
            expected_backend = "subprocess_dev_unisolated" if args.dev_fallback else "microvm"
            ok = ok and body["execution_backend"] == expected_backend and body["cleanup_status"] == "SUCCEEDED"
            ok = ok and body["controller_exchanges"] == body["controller_invocations"] and check["verified"]
            if spec["controller_dt_s"] == 0.01:
                ok = ok and body["controller_invocations"] * 5 == body["trajectory_samples_total"]
        else:
            entry["detail"] = body.get("detail")
            ok = ok and "Guest cleanup: SUCCEEDED" in str(body.get("detail"))
        if not args.dev_fallback:
            entry["residual_sandboxes"] = [n for n in entry["sandboxes_created"] if sandbox_exists(msb, n)]
            ok = ok and len(entry["sandboxes_created"]) == 1 and not entry["residual_sandboxes"]
        entry["passed"] = bool(ok)
        results.append(entry)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: HTTP {resp.status_code}, "
              f"{entry.get('cleanup_status') or entry.get('detail')}")

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "host": platform.node(),
        "platform": platform.platform(),
        "mode": "dev_subprocess_fallback (NOT microVM evidence)" if args.dev_fallback else "microvm",
        "results": results,
        "passed": all(r["passed"] for r in results),
    }
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2))
    print("OVERALL:", "PASS" if report["passed"] else "FAIL")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

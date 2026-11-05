"""Measure a fixed JSON-lines exchange with a running Microsandbox guest.

This is a feasibility probe, not a controller runner or a security boundary.
"""

from __future__ import annotations

import json
import os
import selectors
import statistics
import subprocess
import time

GUEST = """import json,sys
for line in sys.stdin.buffer:
    item=json.loads(line)
    print(json.dumps({'trial_id':item['trial_id'],'step_index':item['step_index']}),flush=True)
"""


def main() -> None:
    command = [
        os.path.expanduser("~/.local/bin/msb"),
        "exec",
        "--stream",
        "domnir-spike",
        "--",
        "python",
        "-u",
        "-c",
        GUEST,
    ]
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert process.stdin and process.stdout and process.stderr
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    buffered = bytearray()
    latency_ms = []
    try:
        for index in range(1000):
            frame = {"trial_id": "fixed-feasibility-fixture", "step_index": index}
            started = time.monotonic()
            process.stdin.write(json.dumps(frame).encode() + b"\n")
            process.stdin.flush()
            while b"\n" not in buffered:
                remaining = 5.0 - (time.monotonic() - started)
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError(f"Frame {index} exceeded the deadline")
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    raise RuntimeError("Guest stream closed before responding")
                buffered.extend(chunk)
                if len(buffered) > 8192:
                    raise ValueError("Guest response exceeded the size limit")
            line, _, rest = buffered.partition(b"\n")
            buffered = bytearray(rest)
            if json.loads(line) != frame:
                raise ValueError(f"Unexpected response for frame {index}")
            latency_ms.append((time.monotonic() - started) * 1000)
        process.stdin.close()
        code = process.wait(timeout=10)
        if code:
            raise RuntimeError(f"Guest command failed with exit status {code}")
        ordered = sorted(latency_ms)
        print(
            json.dumps(
                {
                    "fixture": "fixed_json_echo",
                    "frames": len(latency_ms),
                    "missed_frames": 0,
                    "p50_ms": statistics.median(latency_ms),
                    "p95_ms": ordered[949],
                    "maximum_ms": max(latency_ms),
                },
                indent=2,
            )
        )
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()

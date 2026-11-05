"""Run one bounded fixed-controller integration check on a Linux KVM host."""

import argparse
import json
import uuid
from dataclasses import asdict
from pathlib import Path

from domnir.fixture_trial import run_fixture_trial
from domnir.sandbox import SandboxLease


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--msb", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    lease = SandboxLease(args.msb)
    with lease:
        result = run_fixture_trial(args.model, lease, trial_id=str(uuid.uuid4()))
    record = {
        "fixture_only": True,
        "result": asdict(result),
        "cleanup_succeeded": lease.cleanup_succeeded,
    }
    if args.output:
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(record, output, indent=2, allow_nan=False)
    summary = {
        key: value
        for key, value in record["result"].items()
        if key
        not in {
            "actions",
            "states",
            "replay_states",
            "integration_states",
            "replay_integration_states",
            "model_hashes_sha256",
        }
    }
    print(
        json.dumps(
            {
                "fixture_only": True,
                "result": summary,
                "cleanup_succeeded": lease.cleanup_succeeded,
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()

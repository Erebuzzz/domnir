"""Run a single controller source file in an isolated feasibility guest."""

import argparse
import json
import uuid
from dataclasses import asdict
from pathlib import Path

from domnir.fixture_trial import run_controller_trial
from domnir.sandbox import SandboxLease, validate_controller_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--msb", type=Path, required=True)
    parser.add_argument("--controller", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with args.controller.open("rb") as source_file:
        source = source_file.read(32769)
    if not 1 <= len(source) <= 32768:
        raise ValueError("Controller source must contain 1 to 32768 bytes")
    validate_controller_source(source)
    lease = SandboxLease(args.msb)
    with lease:
        result = run_controller_trial(
            args.model, lease, source, trial_id=str(uuid.uuid4())
        )
    record = {
        "feasibility_only": True,
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
                "feasibility_only": True,
                "result": summary,
                "cleanup_succeeded": lease.cleanup_succeeded,
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()

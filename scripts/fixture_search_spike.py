"""Search a small, declared synthetic envelope with the fixed guest fixture."""

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
    clearance_limit_m = 0.05
    candidates = []
    for initial_altitude in (0.10, 0.15):
        for disturbance in (0.0, -0.05):
            lease = SandboxLease(args.msb)
            with lease:
                result = run_fixture_trial(
                    args.model,
                    lease,
                    trial_id=str(uuid.uuid4()),
                    initial_altitude_m=initial_altitude,
                    vertical_disturbance_n=disturbance,
                )
            candidates.append(
                {
                    "initial_altitude_m": initial_altitude,
                    "vertical_disturbance_n": disturbance,
                    "result": asdict(result),
                    "cleanup_succeeded": lease.cleanup_succeeded,
                }
            )
    worst = min(
        candidates, key=lambda candidate: candidate["result"]["minimum_altitude_m"]
    )
    replay_valid = worst["result"]["replay_max_abs_difference"] <= 1e-12
    record = {
        "fixture_only": True,
        "scenario_count": len(candidates),
        "altitude_limit_m": clearance_limit_m,
        "violation_found": (worst["result"]["minimum_altitude_m"] < clearance_limit_m)
        if replay_valid
        else None,
        "replay_valid": replay_valid,
        "worst_scenario": worst,
        "candidates": candidates,
    }
    if args.output:
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(record, output, indent=2, allow_nan=False)
    for candidate in candidates:
        for key in (
            "actions",
            "states",
            "replay_states",
            "integration_states",
            "replay_integration_states",
            "model_hashes_sha256",
        ):
            candidate["result"].pop(key)
    print(json.dumps(record, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

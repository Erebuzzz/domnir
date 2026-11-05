"""Smoke script: generate controller via Vultr Inference and execute in microVM."""

import uuid
from pathlib import Path
from domnir.fixture_trial import run_controller_trial
from domnir.inference.vultr import VultrInferenceClient
from domnir.sandbox import SandboxLease
from domnir.spec import FlightSpec


def main() -> None:
    print("Generating controller via Vultr Serverless Inference...")
    client = VultrInferenceClient()
    spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.4)
    controller = client.generate_controller(spec, model="glm-5.3-flash")
    print(f"Generated controller hash: {controller.source_sha256}")
    print(f"Generated code preview:\n{controller.source_code[:200]}...")

    msb_bin = Path("/home/domnir/.microsandbox/bin/msb")
    model_path = Path("/home/domnir/menagerie/bitcraze_crazyflie_2/cf2.xml")

    lease = SandboxLease(msb_bin, duration_seconds=60)
    with lease:
        print("Starting microVM and running controller trial (200 steps)...")
        result = run_controller_trial(
            model_path,
            lease,
            controller.source_code.encode("utf-8"),
            trial_id=str(uuid.uuid4()),
            steps=200,
        )
        print(f"Trial finished. Final altitude error: {result.final_altitude_error_m:.6f} m")
        print(f"Replay max abs difference: {result.replay_max_abs_difference:.2e}")
        print(f"Actions executed: {len(result.actions)}")

    print(f"Sandbox cleaned up successfully: {lease.cleanup_succeeded}")


if __name__ == "__main__":
    main()

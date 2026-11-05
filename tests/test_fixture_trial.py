import hashlib
import os
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from domnir.fixture_trial import ChannelError, run_controller_trial, run_fixture_trial
from domnir.protocol import InvalidFrame
from domnir.sandbox import SandboxLease


@unittest.skipUnless(
    os.environ.get("DOMNIR_RUN_KVM_TESTS") == "1",
    "Requires a KVM host and Microsandbox",
)
class LiveFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = Path(os.environ["DOMNIR_SPIKE_MODEL"])
        cls.msb = Path(os.environ["DOMNIR_MSB"])

    def lease(self):
        return SandboxLease(self.msb, duration_seconds=60)

    def assert_removed(self, lease):
        self.assertTrue(lease.cleanup_succeeded)
        output = subprocess.run(
            [self.msb, "list"], capture_output=True, text=True, check=True, timeout=10
        )
        self.assertNotIn(lease.name, output.stdout)

    def test_live_fixture_and_replay(self):
        lease = self.lease()
        with lease:
            result = run_fixture_trial(
                self.model, lease, trial_id=str(uuid.uuid4()), steps=200
            )
            self.assertLess(abs(result.final_altitude_error_m), 0.05)
            self.assertLess(result.replay_max_abs_difference, 1e-12)
            self.assertEqual(len(result.actions), 200)
            self.assertEqual(len(result.states), 201)
            self.assertEqual(len(result.replay_states), 201)
            self.assertEqual(len(result.integration_states), 201)
            self.assertEqual(len(result.replay_integration_states), 201)
            self.assertIn("cf2.xml", result.model_hashes_sha256)
        self.assert_removed(lease)

    def test_downward_disturbance_replays_a_limit_violation(self):
        lease = self.lease()
        with lease:
            result = run_fixture_trial(
                self.model,
                lease,
                trial_id="disturbance",
                steps=200,
                initial_altitude_m=0.10,
                vertical_disturbance_n=-0.05,
            )
            self.assertLess(result.minimum_altitude_m, 0.05)
            self.assertLess(result.replay_max_abs_difference, 1e-12)
        self.assert_removed(lease)

    def test_user_source_runs_in_guest_only_and_replays(self):
        lease = self.lease()
        marker = Path("/tmp") / f"domnir-guest-only-{uuid.uuid4().hex}"
        source = f"""from pathlib import Path
Path({str(marker)!r}).write_text('guest')
def observe(obs):
    return {{'schema_version':'1.0', 'trial_id':obs['trial_id'],
            'step_index':obs['step_index'], 'thrust':0.26487,
            'moment_x':0.0, 'moment_y':0.0, 'moment_z':0.0}}
""".encode()
        self.assertFalse(marker.exists())
        with lease:
            result = run_controller_trial(
                self.model, lease, source, trial_id="guest-only", steps=20
            )
            self.assertEqual(result.source_kind, "guest_controller")
            self.assertIsNone(result.fixture_sha256)
            self.assertEqual(
                result.controller_sha256, hashlib.sha256(source).hexdigest()
            )
            self.assertIsNotNone(result.guest_runner_sha256)
            self.assertLess(result.replay_max_abs_difference, 1e-12)
        self.assertFalse(marker.exists())
        self.assert_removed(lease)

    def test_controller_runtime_failure_cleans_up(self):
        lease = self.lease()
        with self.assertRaises(ChannelError), lease:
            run_controller_trial(
                self.model,
                lease,
                b"raise RuntimeError('fixture')\ndef observe(obs): pass\n",
                trial_id="crash",
                steps=1,
            )
        self.assert_removed(lease)

    def test_controller_output_flood_cleans_up(self):
        lease = self.lease()
        source = (
            b"def observe(obs):\n    print('x' * 8192, flush=True)\n    return {}\n"
        )
        with self.assertRaises(ChannelError), lease:
            run_controller_trial(self.model, lease, source, trial_id="flood", steps=1)
        self.assert_removed(lease)

    def test_controller_hang_cleans_up(self):
        lease = self.lease()
        source = b"def observe(obs):\n    while True: pass\n"
        with self.assertRaises(ChannelError), lease:
            run_controller_trial(
                self.model, lease, source, trial_id="hang", steps=1, timeout_s=0.5
            )
        self.assert_removed(lease)

    def test_controller_out_of_range_action_cleans_up(self):
        lease = self.lease()
        source = b"""def observe(obs):
    return {'schema_version': '1.0', 'trial_id': obs['trial_id'],
            'step_index': obs['step_index'], 'thrust': 99,
            'moment_x': 0, 'moment_y': 0, 'moment_z': 0}
"""
        with self.assertRaises(InvalidFrame), lease:
            run_controller_trial(
                self.model, lease, source, trial_id="bad-action", steps=1
            )
        self.assert_removed(lease)

    def test_malformed_response_fails_and_cleans_up(self):
        lease = self.lease()
        bad_fixture = "import sys; sys.stdin.readline(); print('not-json', flush=True)"
        with (
            patch("domnir.fixture_trial.FIXTURE", bad_fixture),
            self.assertRaises(InvalidFrame),
            lease,
        ):
            run_fixture_trial(self.model, lease, trial_id="bad", steps=1)
        self.assert_removed(lease)

    def test_timeout_fails_and_cleans_up(self):
        lease = self.lease()
        slow_fixture = "import sys,time; sys.stdin.readline(); time.sleep(10)"
        with (
            patch("domnir.fixture_trial.FIXTURE", slow_fixture),
            self.assertRaises(ChannelError),
            lease,
        ):
            run_fixture_trial(
                self.model, lease, trial_id="slow", steps=1, timeout_s=0.1
            )
        self.assert_removed(lease)

    def test_oversized_response_fails_and_cleans_up(self):
        lease = self.lease()
        loud_fixture = "import sys; sys.stdin.readline(); print('x' * 8192, flush=True)"
        with (
            patch("domnir.fixture_trial.FIXTURE", loud_fixture),
            self.assertRaises(ChannelError),
            lease,
        ):
            run_fixture_trial(self.model, lease, trial_id="loud", steps=1)
        self.assert_removed(lease)

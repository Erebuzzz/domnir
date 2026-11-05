import json
import os
import unittest
from pathlib import Path

import numpy as np

from domnir.protocol import InvalidFrame
from domnir.simulation import run_trial


class TrustedSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        default = (
            Path(__file__).resolve().parents[1]
            / ".cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml"
        )
        cls.model = Path(os.environ.get("DOMNIR_SPIKE_MODEL", str(default)))
        if not cls.model.exists():
            raise unittest.SkipTest("Menagerie model not available")

    def frame(self, step, thrust):
        return json.dumps(
            {
                "schema_version": "1.0",
                "trial_id": "trial",
                "step_index": step,
                "thrust": thrust,
                "moment_x": 0,
                "moment_y": 0,
                "moment_z": 0,
            }
        ).encode()

    def test_records_and_replays_nonstationary_trajectory(self):
        result = run_trial(
            self.model, "trial", [self.frame(i, 0.2) for i in range(100)]
        )
        self.assertEqual(result.actions.shape, (100, 4))
        self.assertEqual(result.states.shape, (101, 13))
        self.assertLess(result.states[-1, 2], result.states[0, 2])
        self.assertTrue(np.isfinite(result.states).all())
        self.assertLess(result.replay_max_abs_difference, 1e-12)

    def test_invalid_or_empty_trials_fail_closed(self):
        with self.assertRaises(InvalidFrame):
            run_trial(self.model, "trial", [self.frame(1, 0.2)])
        with self.assertRaises(InvalidFrame):
            run_trial(self.model, "trial", [self.frame(0, 0.9)])
        with self.assertRaises(ValueError):
            run_trial(self.model, "trial", [])


if __name__ == "__main__":
    unittest.main()

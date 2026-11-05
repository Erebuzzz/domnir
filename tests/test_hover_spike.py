import importlib.util
import os
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hover_spike.py"
SPEC = importlib.util.spec_from_file_location("hover_spike", SCRIPT)
assert SPEC and SPEC.loader
spike = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(spike)


class HoverSpikeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        default = (
            Path(__file__).resolve().parents[1]
            / ".cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml"
        )
        cls.model = Path(os.environ.get("DOMNIR_SPIKE_MODEL", str(default)))
        if not cls.model.exists():
            raise unittest.SkipTest("Menagerie model not available")

    def test_hover_replays_and_records_provenance(self):
        result = spike.run(self.model, 1000)
        self.assertEqual(result["status"], "local_hover_spike_only")
        self.assertIn("cf2.xml", result["model_hashes_sha256"])
        self.assertGreater(len(result["model_hashes_sha256"]), 1)
        self.assertAlmostEqual(result["hover_thrust_n"], 0.027 * 9.81)
        self.assertLess(
            abs(result["final_altitude_error_m"]), result["initial_altitude_offset_m"]
        )
        self.assertLess(result["replay_max_abs_state_difference"], 1e-12)

    def test_rejects_invalid_step_budget(self):
        for steps in (0, -1, 100001):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                spike.run(self.model, steps)


if __name__ == "__main__":
    unittest.main()

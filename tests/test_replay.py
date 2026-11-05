import os
import platform
import unittest
from pathlib import Path

import mujoco
import numpy as np

from domnir.replay import (
    INTEGRATION_SIGNATURE,
    capture_integration_state,
    model_hashes,
    replay_saved_trajectory,
    restore_integration_state,
)


class IntegrationStateTests(unittest.TestCase):
    def test_round_trip_preserves_warmstart_controls_time_and_forces(self):
        model = mujoco.MjModel.from_xml_string("""<mujoco>
          <worldbody><body name="box"><freejoint/><geom type="sphere" size="0.05" mass="1"/><site name="act"/></body></worldbody>
          <actuator><motor site="act" gear="0 0 1 0 0 0"/></actuator>
        </mujoco>""")
        original = mujoco.MjData(model)
        original.time = 1.25
        original.qpos[2] = 0.7
        original.qvel[2] = -0.2
        original.qacc_warmstart[:] = np.arange(model.nv) * 0.01
        original.ctrl[0] = 0.12
        original.xfrc_applied[1, 2] = -0.03
        saved = capture_integration_state(model, original)
        restored = mujoco.MjData(model)
        restore_integration_state(model, restored, saved)
        np.testing.assert_array_equal(capture_integration_state(model, restored), saved)
        self.assertEqual(restored.time, 1.25)
        np.testing.assert_array_equal(restored.qacc_warmstart, original.qacc_warmstart)
        np.testing.assert_array_equal(restored.ctrl, original.ctrl)
        np.testing.assert_array_equal(restored.xfrc_applied, original.xfrc_applied)
        mujoco.mj_step(model, original)
        mujoco.mj_step(model, restored)
        np.testing.assert_allclose(
            capture_integration_state(model, original),
            capture_integration_state(model, restored),
            rtol=0,
            atol=1e-12,
        )

    def test_rejects_invalid_or_nonfinite_state(self):
        model = mujoco.MjModel.from_xml_string("<mujoco/>")
        data = mujoco.MjData(model)
        with self.assertRaises(ValueError):
            restore_integration_state(model, data, np.array([1.0, 2.0]))
        state = capture_integration_state(model, data)
        state[0] = np.nan
        with self.assertRaises(ValueError):
            restore_integration_state(model, data, state)

    def test_saved_trajectory_can_be_replayed_and_tampering_is_rejected(self):
        default = (
            Path(__file__).resolve().parents[1]
            / ".cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml"
        )
        model_path = Path(os.environ.get("DOMNIR_SPIKE_MODEL", str(default)))
        if not model_path.exists():
            self.skipTest("Menagerie model not available")
        model = mujoco.MjModel.from_xml_path(str(model_path))
        data = mujoco.MjData(model)
        body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
        actions = [[0.26487, 0.0, 0.0, 0.0] for _ in range(10)]
        states = [capture_integration_state(model, data).tolist()]
        for action in actions:
            data.ctrl[:] = action
            data.xfrc_applied[body_id, 2] = -0.02
            mujoco.mj_step(model, data)
            states.append(capture_integration_state(model, data).tolist())
        result = {
            "mujoco_version": mujoco.__version__,
            "platform": platform.platform(),
            "integration_signature": INTEGRATION_SIGNATURE,
            "model_hashes_sha256": model_hashes(model_path),
            "steps": len(actions),
            "timestep_s": float(model.opt.timestep),
            "actions": actions,
            "integration_states": states,
            "vertical_disturbance_n": -0.02,
        }
        self.assertLess(
            replay_saved_trajectory(model_path, result, tolerance=1e-12), 1e-12
        )
        result["actions"][0][0] = 0.1
        with self.assertRaises(ValueError):
            replay_saved_trajectory(model_path, result, tolerance=1e-12)

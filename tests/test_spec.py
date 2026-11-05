"""Unit tests for flight specification and generated controller validation."""

import hashlib
import unittest

from domnir.sandbox import validate_controller_source
from domnir.spec import FlightSpec, GeneratedController


class SpecTests(unittest.TestCase):
    def test_default_flight_spec_is_valid(self):
        spec = FlightSpec()
        self.assertEqual(spec.target_altitude_m, 0.1)
        self.assertEqual(spec.step_budget, 200)
        self.assertEqual(spec.dt_s, 0.002)

    def test_rejects_inverted_altitude_bounds(self):
        with self.assertRaises(ValueError):
            FlightSpec(min_allowed_altitude_m=0.5, max_allowed_altitude_m=0.2)

    def test_rejects_target_outside_allowed_envelope(self):
        with self.assertRaises(ValueError):
            FlightSpec(target_altitude_m=0.03, min_allowed_altitude_m=0.05, max_allowed_altitude_m=1.0)
        with self.assertRaises(ValueError):
            FlightSpec(target_altitude_m=1.5, min_allowed_altitude_m=0.05, max_allowed_altitude_m=1.0)

    def test_rejects_inverted_disturbance_range(self):
        with self.assertRaises(ValueError):
            FlightSpec(disturbance_force_z_min=0.1, disturbance_force_z_max=-0.1)

    def test_valid_controller_is_accepted_and_matches_sandbox_validator(self):
        source = (
            "def observe(observation):\n"
            "    alt = observation['position_m'][2]\n"
            "    vel = observation['velocity_mps'][2]\n"
            "    thrust = max(0.0, min(0.35, 0.26487 + 0.15 * (0.1 - alt) - 0.08 * vel))\n"
            "    return {\n"
            "        'schema_version': '1.0',\n"
            "        'trial_id': observation['trial_id'],\n"
            "        'step_index': observation['step_index'],\n"
            "        'thrust': thrust,\n"
            "        'moment_x': 0.0,\n"
            "        'moment_y': 0.0,\n"
            "        'moment_z': 0.0,\n"
            "    }\n"
        )
        controller = GeneratedController.from_source(source, model_id="glm-5.3-flash")
        self.assertEqual(controller.model_id, "glm-5.3-flash")
        self.assertEqual(controller.source_sha256, hashlib.sha256(source.encode("utf-8")).hexdigest())

        sandbox_hash = validate_controller_source(source.encode("utf-8"))
        self.assertEqual(controller.source_sha256, sandbox_hash)

    def test_rejects_syntax_error(self):
        bad_source = "def observe(observation):\n    return {{invalid syntax"
        with self.assertRaises(ValueError) as ctx:
            GeneratedController.from_source(bad_source, model_id="test-model")
        self.assertIn("not valid Python", str(ctx.exception))

    def test_rejects_missing_observe_function(self):
        bad_source = "def control(obs):\n    return {}\n"
        with self.assertRaises(ValueError) as ctx:
            GeneratedController.from_source(bad_source, model_id="test-model")
        self.assertIn("observe function", str(ctx.exception))

    def test_rejects_observe_function_with_wrong_arity(self):
        bad_source = "def observe(obs, extra):\n    return {}\n"
        with self.assertRaises(ValueError) as ctx:
            GeneratedController.from_source(bad_source, model_id="test-model")
        self.assertIn("exactly one argument", str(ctx.exception))

    def test_rejects_oversized_source(self):
        huge_source = "def observe(observation):\n    pass\n" + "#" * 35000
        with self.assertRaises(ValueError) as ctx:
            GeneratedController.from_source(huge_source, model_id="test-model")
        self.assertIn("32768 bytes", str(ctx.exception))

    def test_rejects_tampered_hash(self):
        source = "def observe(observation):\n    return {}\n"
        with self.assertRaises(ValueError) as ctx:
            GeneratedController(
                source_code=source,
                model_id="test-model",
                source_sha256="0" * 64,
            )
        self.assertIn("Source hash mismatch", str(ctx.exception))

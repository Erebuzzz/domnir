import json
import unittest

from domnir.protocol import ActionBounds, InvalidFrame, parse_action


class ActionProtocolTests(unittest.TestCase):
    def setUp(self):
        self.bounds = ActionBounds((0.0, -1.0, -1.0, -1.0), (0.35, 1.0, 1.0, 1.0))
        self.frame = {
            "schema_version": "1.0",
            "trial_id": "trial",
            "step_index": 4,
            "thrust": 0.25,
            "moment_x": 0.0,
            "moment_y": 0.0,
            "moment_z": 0.0,
        }

    def parse(self, payload):
        return parse_action(payload, trial_id="trial", step_index=4, bounds=self.bounds)

    def test_accepts_bounded_matching_action(self):
        self.assertEqual(
            self.parse(json.dumps(self.frame).encode()), (0.25, 0.0, 0.0, 0.0)
        )

    def test_rejects_untrusted_inputs(self):
        bad = [
            {**self.frame, "step_index": True},
            {**self.frame, "trial_id": "other"},
            {**self.frame, "thrust": True},
            {**self.frame, "thrust": float("nan")},
            {**self.frame, "thrust": 0.36},
            {**self.frame, "extra": 1},
            {key: value for key, value in self.frame.items() if key != "moment_z"},
        ]
        for frame in bad:
            with self.subTest(frame=frame), self.assertRaises(InvalidFrame):
                self.parse(json.dumps(frame).encode())
        for payload in (b"", b"x" * 4097, b"\xff", b'{"x":1,"x":2}'):
            with self.subTest(payload=payload[:20]), self.assertRaises(InvalidFrame):
                self.parse(payload)

    def test_rejects_bad_bounds(self):
        with self.assertRaises(ValueError):
            ActionBounds((0, 0, 0, 0), (1, 1, float("inf"), 1))
        with self.assertRaises(ValueError):
            ActionBounds((1, 0, 0, 0), (0, 1, 1, 1))


if __name__ == "__main__":
    unittest.main()

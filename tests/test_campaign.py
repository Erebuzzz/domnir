import copy
import unittest

from domnir.campaign import ALTITUDE_LIMIT_M, build_record, scenario_suite
from domnir.replay import INTEGRATION_SIGNATURE


class CampaignTests(unittest.TestCase):
    def entries(self):
        entries = []
        for scenario in scenario_suite(42):
            state = [0.0] * 13
            state[2] = scenario["initial_altitude_m"]
            states = [state.copy() for _ in range(201)]
            entries.append(
                {
                    "scenario": scenario,
                    "cleanup_succeeded": True,
                    "result": {
                        "controller_sha256": "source",
                        "source_kind": "guest_controller",
                        "guest_runner_sha256": "runner",
                        "initial_altitude_m": scenario["initial_altitude_m"],
                        "vertical_disturbance_n": scenario["vertical_disturbance_n"],
                        "model_hashes_sha256": {"cf2.xml": "model"},
                        "runtime_version": "msb",
                        "guest_image": "image",
                        "mujoco_version": "3.3.7",
                        "timestep_s": 0.002,
                        "steps": 200,
                        "states": copy.deepcopy(states),
                        "replay_states": copy.deepcopy(states),
                        "actions": [[0.0] * 4 for _ in range(200)],
                        "replay_max_abs_difference": 0.0,
                        "integration_signature": INTEGRATION_SIGNATURE,
                        "integration_states": [
                            [0.0, *row, *([0.0] * 6)] for row in states
                        ],
                        "replay_integration_states": [
                            [0.0, *row, *([0.0] * 6)] for row in states
                        ],
                    },
                }
            )
        return entries

    def test_seeded_suite_is_reproducible_and_bounded(self):
        self.assertEqual(scenario_suite(42), scenario_suite(42))
        self.assertNotEqual(scenario_suite(42), scenario_suite(43))
        self.assertEqual(len(scenario_suite(42)), 8)
        for scenario in scenario_suite(42):
            self.assertTrue(0.10 <= scenario["initial_altitude_m"] <= 0.15)
            self.assertTrue(-0.05 <= scenario["vertical_disturbance_n"] <= 0.0)

    def test_replayed_violation_is_distinct_from_qualification_and_containment(self):
        entries = self.entries()
        for trace in (
            entries[1]["result"]["states"],
            entries[1]["result"]["replay_states"],
        ):
            trace[-1][2] = ALTITUDE_LIMIT_M - 0.01
        for trace in (
            entries[1]["result"]["integration_states"],
            entries[1]["result"]["replay_integration_states"],
        ):
            trace[-1][3] = ALTITUDE_LIMIT_M - 0.01
        result = build_record(42, "source", entries)
        self.assertEqual(result["flight"]["finding"], "VIOLATION_FOUND")
        self.assertEqual(result["flight"]["qualification"], "INCONCLUSIVE")
        self.assertEqual(result["containment"]["status"], "NOT_TESTED")
        self.assertEqual(result["replay"]["status"], "MATCHED")
        self.assertEqual(result["provenance"]["status"], "INCOMPLETE")

    def test_failed_scenario_cannot_produce_no_violation_result(self):
        entries = self.entries()
        entries[0]["result"] = None
        result = build_record(42, "source", entries)
        self.assertEqual(result["flight"]["finding"], "INCONCLUSIVE")
        self.assertEqual(result["campaign"]["failed"], 1)

    def test_tampered_trace_source_or_cleanup_invalidates_findings(self):
        for mutation in ("trace", "source", "cleanup", "runner"):
            entries = self.entries()
            if mutation == "trace":
                entries[0]["result"]["replay_states"][1][2] += 0.01
            elif mutation == "source":
                entries[0]["result"]["controller_sha256"] = "other"
            elif mutation == "cleanup":
                entries[0]["cleanup_succeeded"] = False
            else:
                entries[1]["result"]["guest_runner_sha256"] = "other"
            with self.subTest(mutation=mutation):
                self.assertEqual(
                    build_record(42, "source", entries)["flight"]["finding"], "INVALID"
                )

    def test_full_integration_replay_divergence_is_invalid(self):
        entries = self.entries()
        entries[0]["result"]["replay_integration_states"][1][-1] = 0.01
        entries[0]["result"]["replay_max_abs_difference"] = 0.01
        record = build_record(42, "source", entries)
        self.assertEqual(record["replay"]["status"], "DIVERGED")
        self.assertEqual(record["flight"]["finding"], "INVALID")

    def test_missing_full_state_cannot_produce_positive_finding(self):
        entries = self.entries()
        del entries[0]["result"]["integration_states"]
        self.assertEqual(
            build_record(42, "source", entries)["flight"]["finding"], "INVALID"
        )

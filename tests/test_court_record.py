"""Unit and integration tests for Court Record generation and independent replay verification."""

import copy
import hashlib
import os
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

import mujoco
import numpy as np

from domnir.api.app import app, orchestrator
from domnir.api.jobs import file_hashes, get_default_model_path
from domnir.court_record import (
    LIMITATIONS,
    REPLAY_TOLERANCE,
    SCHEMA_VERSION,
    build_court_record,
    chain_events,
    compute_trajectory_hash,
    verify_court_record,
    verify_event_chain,
)
from domnir.replay import (
    INTEGRATION_SIGNATURE,
    capture_integration_state,
    restore_integration_state,
)
from domnir.sandbox import RUNTIME_VERSION
from domnir.spec import FlightSpec, GeneratedController

SAMPLE_CONTROLLER = """
def observe(observation):
    z = observation['position_m'][2]
    vz = observation['velocity_mps'][2]
    thrust = max(0.0, min(0.35, 0.26487 + 0.15 * (0.1 - z) - 0.08 * vz))
    return {
        'schema_version': '1.0',
        'trial_id': observation['trial_id'],
        'step_index': observation['step_index'],
        'thrust': thrust,
        'moment_x': 0.0,
        'moment_y': 0.0,
        'moment_z': 0.0,
    }
""".strip()


def run_test_simulation(
    model_path: Path, steps: int = 10, disturbance: float = 0.0
) -> dict:
    model = mujoco.MjModel.from_xml_path(str(model_path))
    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
    data = mujoco.MjData(model)
    data.qpos[2] = 0.15

    init_state = capture_integration_state(model, data)
    integration_states = [init_state.tolist()]
    positions = [data.qpos[:3].tolist()]
    velocities = [data.qvel[:3].tolist()]
    timestamps = [0.0]
    actions = []

    for idx in range(steps):
        z = data.qpos[2]
        vz = data.qvel[2]
        thrust = max(0.0, min(0.35, 0.26487 + 0.15 * (0.1 - z) - 0.08 * vz))
        action = [thrust, 0.0, 0.0, 0.0]
        actions.append(action)

        data.ctrl[:] = action
        data.xfrc_applied[body_id, 2] = disturbance
        mujoco.mj_step(model, data)

        timestamps.append(float(data.time))
        positions.append(data.qpos[:3].tolist())
        velocities.append(data.qvel[:3].tolist())
        integration_states.append(capture_integration_state(model, data).tolist())

    return {
        "steps": steps,
        "timestamps": timestamps,
        "positions": positions,
        "velocities": velocities,
        "actions": actions,
        "integration_states": integration_states,
        "timestep_s": float(model.opt.timestep),
    }


class CourtRecordGenerationTests(unittest.TestCase):
    def setUp(self):
        self.model_path = get_default_model_path()
        self.spec = FlightSpec(
            target_altitude_m=0.1,
            altitude_tolerance_m=0.05,
            min_allowed_altitude_m=0.05,
            max_allowed_altitude_m=0.5,
            mission_duration_s=0.2,
        )

    def test_build_court_record_contains_all_required_m3_fields(self):
        sim = run_test_simulation(self.model_path, steps=5)
        raw_events = [
            {"event_type": "job_created", "details": {"id": "exp-1"}},
            {"event_type": "simulation_started", "details": {"steps": 5}},
            {"event_type": "simulation_completed", "details": {"diff": 0.0}},
        ]

        record = build_court_record(
            experiment_id="exp-1",
            spec=self.spec,
            scenario_seed=42,
            initial_altitude_m=0.15,
            vertical_disturbance_n=0.0,
            steps=sim["steps"],
            timestep_s=sim["timestep_s"],
            controller_source=SAMPLE_CONTROLLER,
            controller_model_id="glm-5.3-flash",
            prompt_metadata={"prompt_version": "v1"},
            model_path=self.model_path,
            timestamps=sim["timestamps"],
            position_m=sim["positions"],
            velocity_mps=sim["velocities"],
            actions=sim["actions"],
            integration_states=sim["integration_states"],
            replay_max_abs_diff=0.0,
            replay_matched=True,
            flight_verdict="NOT_FALSIFIED",
            verdict_reason="All constraints satisfied",
            execution_backend="trusted_simulator",
            cleanup_succeeded=True,
            raw_events=raw_events,
        )

        self.assertEqual(record["schema_version"], SCHEMA_VERSION)
        self.assertTrue(record["record_id"].startswith("cr-"))
        self.assertEqual(record["experiment_id"], "exp-1")
        self.assertEqual(record["verdict"], "NOT_FALSIFIED")
        self.assertEqual(record["execution_backend"], "trusted_simulator")

        scenario = record["scenario"]
        self.assertEqual(scenario["seed"], 42)
        self.assertEqual(scenario["initial_altitude_m"], 0.15)
        self.assertEqual(scenario["steps"], 5)
        self.assertEqual(scenario["vertical_disturbance_n"], 0.0)

        controller = record["controller"]
        self.assertEqual(controller["source_code"], SAMPLE_CONTROLLER)
        expected_src_sha = hashlib.sha256(SAMPLE_CONTROLLER.encode("utf-8")).hexdigest()
        self.assertEqual(controller["source_sha256"], expected_src_sha)
        self.assertEqual(controller["model_id"], "glm-5.3-flash")
        self.assertEqual(controller["prompt_metadata"]["prompt_version"], "v1")

        simulator = record["simulator"]
        self.assertEqual(simulator["engine"], "mujoco")
        self.assertEqual(simulator["runtime_version"], RUNTIME_VERSION)
        self.assertIn("cf2.xml", simulator["model_hashes_sha256"])
        self.assertEqual(simulator["integration_signature"], INTEGRATION_SIGNATURE)

        trajectory = record["trajectory"]
        self.assertEqual(trajectory["steps"], 5)
        self.assertEqual(len(trajectory["timestamps"]), 6)
        self.assertEqual(len(trajectory["position_m"]), 6)
        self.assertEqual(len(trajectory["velocity_mps"]), 6)
        self.assertEqual(len(trajectory["actions"]), 5)
        self.assertEqual(len(trajectory["integration_states"]), 6)
        self.assertTrue(len(trajectory["trajectory_sha256"]) == 64)

        replay = record["replay"]
        self.assertEqual(replay["verdict"], "MATCHED")
        self.assertEqual(replay["tolerance"], REPLAY_TOLERANCE)
        self.assertEqual(replay["max_abs_difference"], 0.0)

        event_log = record["event_log"]
        self.assertEqual(event_log["event_count"], 3)
        self.assertEqual(event_log["chain_integrity"], "VERIFIED")
        self.assertTrue(len(event_log["head_sha256"]) == 64)

        verdicts = record["verdicts"]
        self.assertEqual(verdicts["flight_verdict"], "NOT_FALSIFIED")
        self.assertEqual(verdicts["flight_qualification"], "INCONCLUSIVE")
        self.assertEqual(verdicts["containment_status"], "PARTIAL")
        self.assertEqual(verdicts["provenance_status"], "VERIFIED")
        self.assertEqual(verdicts["cleanup_status"], "SUCCEEDED")

        self.assertEqual(record["limitations"], LIMITATIONS)


class IndependentReplayVerificationTests(unittest.TestCase):
    def setUp(self):
        self.model_path = get_default_model_path()
        self.spec = FlightSpec(
            target_altitude_m=0.1,
            altitude_tolerance_m=0.05,
            min_allowed_altitude_m=0.05,
            max_allowed_altitude_m=0.5,
            mission_duration_s=0.2,
        )
        sim = run_test_simulation(self.model_path, steps=8, disturbance=0.0)
        self.sim = sim
        self.record = build_court_record(
            experiment_id="exp-replay",
            spec=self.spec,
            scenario_seed=101,
            initial_altitude_m=0.15,
            vertical_disturbance_n=0.0,
            steps=sim["steps"],
            timestep_s=sim["timestep_s"],
            controller_source=SAMPLE_CONTROLLER,
            controller_model_id="glm-5.3-flash",
            prompt_metadata={"prompt_version": "v1"},
            model_path=self.model_path,
            timestamps=sim["timestamps"],
            position_m=sim["positions"],
            velocity_mps=sim["velocities"],
            actions=sim["actions"],
            integration_states=sim["integration_states"],
            replay_max_abs_diff=0.0,
            replay_matched=True,
            flight_verdict="NOT_FALSIFIED",
            verdict_reason="All constraints satisfied",
            execution_backend="microvm",
            cleanup_succeeded=True,
            raw_events=[
                {"event_type": "start", "details": {}},
                {"event_type": "finish", "details": {}},
            ],
        )

    def test_independent_verification_succeeds_on_valid_record(self):
        result = verify_court_record(self.record, model_path=self.model_path)
        self.assertTrue(result["verified"])
        self.assertEqual(result["replay_verdict"], "MATCHED")
        self.assertLessEqual(result["replay_max_abs_difference"], REPLAY_TOLERANCE)
        self.assertTrue(result["controller_hash_matched"])
        self.assertTrue(result["trajectory_hash_matched"])
        self.assertTrue(result["model_hashes_matched"])
        self.assertTrue(result["event_chain_verified"])
        self.assertEqual(len(result["errors"]), 0)

    def test_tamper_detection_mutated_controller_source(self):
        tampered = copy.deepcopy(self.record)
        tampered["controller"]["source_code"] = SAMPLE_CONTROLLER + "\n# malicious extra line"

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertFalse(result["controller_hash_matched"])
        self.assertTrue(any("Controller SHA-256 mismatch" in e for e in result["errors"]))

    def test_tamper_detection_mutated_controller_source_hash(self):
        tampered = copy.deepcopy(self.record)
        tampered["controller"]["source_sha256"] = "0" * 64

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertFalse(result["controller_hash_matched"])

    def test_tamper_detection_mutated_trajectory_state(self):
        tampered = copy.deepcopy(self.record)
        tampered["trajectory"]["integration_states"][2][1] += 0.05

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertFalse(result["trajectory_hash_matched"])
        self.assertTrue(any("Trajectory SHA-256 mismatch" in e for e in result["errors"]))

    def test_tamper_detection_forged_trajectory_hash_diverges_replay(self):
        tampered = copy.deepcopy(self.record)
        tampered["trajectory"]["integration_states"][3][1] += 0.05
        traj = tampered["trajectory"]
        forged_sha = compute_trajectory_hash(
            steps=traj["steps"],
            timestamps=traj["timestamps"],
            position_m=traj["position_m"],
            velocity_mps=traj["velocity_mps"],
            actions=traj["actions"],
            integration_states=traj["integration_states"],
        )
        tampered["trajectory"]["trajectory_sha256"] = forged_sha

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertTrue(result["trajectory_hash_matched"])
        self.assertEqual(result["replay_verdict"], "DIVERGED")
        self.assertGreater(result["replay_max_abs_difference"], REPLAY_TOLERANCE)

    def test_tamper_detection_mutated_trajectory_action(self):
        tampered = copy.deepcopy(self.record)
        tampered["trajectory"]["actions"][0][0] = 0.35
        traj = tampered["trajectory"]
        forged_sha = compute_trajectory_hash(
            steps=traj["steps"],
            timestamps=traj["timestamps"],
            position_m=traj["position_m"],
            velocity_mps=traj["velocity_mps"],
            actions=traj["actions"],
            integration_states=traj["integration_states"],
        )
        tampered["trajectory"]["trajectory_sha256"] = forged_sha

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertEqual(result["replay_verdict"], "DIVERGED")

    def test_tamper_detection_mutated_model_hash(self):
        tampered = copy.deepcopy(self.record)
        tampered["simulator"]["model_hashes_sha256"]["cf2.xml"] = "f" * 64

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertFalse(result["model_hashes_matched"])
        self.assertTrue(any("Model file SHA-256 hashes" in e for e in result["errors"]))

    def test_tamper_detection_broken_event_chain_payload(self):
        tampered = copy.deepcopy(self.record)
        tampered["event_log"]["events"][0]["details"]["tampered"] = True

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertFalse(result["event_chain_verified"])

    def test_tamper_detection_broken_event_chain_head(self):
        tampered = copy.deepcopy(self.record)
        tampered["event_log"]["head_sha256"] = "1" * 64

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertFalse(result["event_chain_verified"])

    def test_tamper_detection_broken_event_chain_count(self):
        tampered = copy.deepcopy(self.record)
        tampered["event_log"]["event_count"] = 999

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertFalse(result["event_chain_verified"])

    def test_tamper_detection_forged_position_diverges_replay(self):
        tampered = copy.deepcopy(self.record)
        tampered["trajectory"]["position_m"][2][2] += 0.1
        traj = tampered["trajectory"]
        tampered["trajectory"]["trajectory_sha256"] = compute_trajectory_hash(
            steps=traj["steps"],
            timestamps=traj["timestamps"],
            position_m=traj["position_m"],
            velocity_mps=traj["velocity_mps"],
            actions=traj["actions"],
            integration_states=traj["integration_states"],
        )

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertEqual(result["replay_verdict"], "DIVERGED")
        self.assertGreater(result["replay_max_abs_difference"], REPLAY_TOLERANCE)

    def test_tamper_detection_forged_velocity_diverges_replay(self):
        tampered = copy.deepcopy(self.record)
        tampered["trajectory"]["velocity_mps"][1][2] += 0.2
        traj = tampered["trajectory"]
        tampered["trajectory"]["trajectory_sha256"] = compute_trajectory_hash(
            steps=traj["steps"],
            timestamps=traj["timestamps"],
            position_m=traj["position_m"],
            velocity_mps=traj["velocity_mps"],
            actions=traj["actions"],
            integration_states=traj["integration_states"],
        )

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertEqual(result["replay_verdict"], "DIVERGED")

    def test_tamper_detection_dishonest_flight_qualification_rejected(self):
        tampered = copy.deepcopy(self.record)
        tampered["verdicts"]["flight_qualification"] = "PROVEN_SAFE"

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertTrue(any("Flight qualification must be INCONCLUSIVE" in e for e in result["errors"]))

    def test_tamper_detection_invalid_schema_version_rejected(self):
        tampered = copy.deepcopy(self.record)
        tampered["schema_version"] = "unknown-v9"

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertTrue(any("Unsupported schema version" in e for e in result["errors"]))

    def test_tamper_detection_missing_or_empty_limitations(self):
        tampered = copy.deepcopy(self.record)
        tampered["limitations"] = []

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertTrue(any("limitations" in e for e in result["errors"]))

    def test_tamper_detection_malformed_sections_no_crash(self):
        tampered = copy.deepcopy(self.record)
        tampered["simulator"] = "not_a_dictionary"
        tampered["scenario"] = "not_a_dictionary"

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertTrue(any("simulator section" in e for e in result["errors"]))

    def test_tamper_detection_invalid_step_count_rejected(self):
        tampered = copy.deepcopy(self.record)
        tampered["trajectory"]["steps"] = 0

        result = verify_court_record(tampered, model_path=self.model_path)
        self.assertFalse(result["verified"])
        self.assertEqual(result["replay_verdict"], "INVALID")

    def test_canonical_json_and_compute_trajectory_hash_numpy_arrays(self):
        traj = self.record["trajectory"]
        hash_from_lists = compute_trajectory_hash(
            steps=traj["steps"],
            timestamps=traj["timestamps"],
            position_m=traj["position_m"],
            velocity_mps=traj["velocity_mps"],
            actions=traj["actions"],
            integration_states=traj["integration_states"],
        )
        hash_from_arrays = compute_trajectory_hash(
            steps=traj["steps"],
            timestamps=np.array(traj["timestamps"]),
            position_m=np.array(traj["position_m"]),
            velocity_mps=np.array(traj["velocity_mps"]),
            actions=np.array(traj["actions"]),
            integration_states=np.array(traj["integration_states"]),
        )
        self.assertEqual(hash_from_lists, hash_from_arrays)


class CourtRecordApiEndpointsTests(unittest.TestCase):
    def setUp(self):
        self._prev_fallback = os.environ.get("DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK")
        os.environ["DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK"] = "1"
        self.client = TestClient(app)

    def tearDown(self):
        if self._prev_fallback is not None:
            os.environ["DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK"] = self._prev_fallback
        else:
            os.environ.pop("DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK", None)

    def test_get_court_record_returns_200_and_valid_structure(self):
        payload = {
            "spec": {
                "target_altitude_m": 0.1,
                "altitude_tolerance_m": 0.05,
                "min_allowed_altitude_m": 0.05,
                "max_allowed_altitude_m": 0.5,
                "mission_duration_s": 0.02,
                "dt_s": 0.002,
                "disturbance_force_z_min": 0.0,
                "disturbance_force_z_max": 0.0,
            },
            "controller_source": SAMPLE_CONTROLLER,
            "steps": 5,
            "initial_altitude_m": 0.15,
            "vertical_disturbance_n": 0.0,
            "seed": 42,
            "run_async": False,
        }
        run_resp = self.client.post("/experiments/run", json=payload)
        self.assertEqual(run_resp.status_code, 200)
        exp_id = run_resp.json()["id"]

        cr_resp = self.client.get(f"/experiments/{exp_id}/court-record")
        self.assertEqual(cr_resp.status_code, 200)
        record = cr_resp.json()

        self.assertEqual(record["schema_version"], SCHEMA_VERSION)
        self.assertEqual(record["experiment_id"], exp_id)
        self.assertIn("trajectory", record)
        self.assertIn("verdicts", record)
        self.assertEqual(record["verdicts"]["flight_qualification"], "INCONCLUSIVE")
        self.assertEqual(record["verdicts"]["cleanup_status"], "SUCCEEDED")

    def test_get_court_record_404_for_unknown_experiment(self):
        cr_resp = self.client.get("/experiments/non-existent-experiment-xyz/court-record")
        self.assertEqual(cr_resp.status_code, 404)

    def test_post_court_record_verify_valid(self):
        payload = {
            "spec": {
                "target_altitude_m": 0.1,
                "altitude_tolerance_m": 0.05,
                "min_allowed_altitude_m": 0.05,
                "max_allowed_altitude_m": 0.5,
                "mission_duration_s": 0.02,
                "dt_s": 0.002,
            },
            "controller_source": SAMPLE_CONTROLLER,
            "steps": 5,
            "initial_altitude_m": 0.15,
            "run_async": False,
        }
        run_resp = self.client.post("/experiments/run", json=payload)
        exp_id = run_resp.json()["id"]

        cr_resp = self.client.get(f"/experiments/{exp_id}/court-record")
        record = cr_resp.json()

        verify_resp = self.client.post("/court-records/verify", json=record)
        self.assertEqual(verify_resp.status_code, 200)
        verify_data = verify_resp.json()

        self.assertTrue(verify_data["verified"])
        self.assertEqual(verify_data["replay_verdict"], "MATCHED")
        self.assertTrue(verify_data["controller_hash_matched"])
        self.assertTrue(verify_data["trajectory_hash_matched"])
        self.assertTrue(verify_data["model_hashes_matched"])
        self.assertTrue(verify_data["event_chain_verified"])

    def test_post_court_record_verify_wrapped_object(self):
        payload = {
            "spec": {
                "target_altitude_m": 0.1,
                "altitude_tolerance_m": 0.05,
                "min_allowed_altitude_m": 0.05,
                "max_allowed_altitude_m": 0.5,
                "mission_duration_s": 0.02,
                "dt_s": 0.002,
            },
            "controller_source": SAMPLE_CONTROLLER,
            "steps": 5,
            "initial_altitude_m": 0.15,
            "run_async": False,
        }
        run_resp = self.client.post("/experiments/run", json=payload)
        exp_id = run_resp.json()["id"]

        cr_resp = self.client.get(f"/experiments/{exp_id}/court-record")
        record = cr_resp.json()

        verify_resp = self.client.post("/court-records/verify", json={"court_record": record})
        self.assertEqual(verify_resp.status_code, 200)
        verify_data = verify_resp.json()
        self.assertTrue(verify_data["verified"])

    def test_post_court_record_verify_tampered_detects_failure(self):
        payload = {
            "spec": {
                "target_altitude_m": 0.1,
                "altitude_tolerance_m": 0.05,
                "min_allowed_altitude_m": 0.05,
                "max_allowed_altitude_m": 0.5,
                "mission_duration_s": 0.02,
                "dt_s": 0.002,
            },
            "controller_source": SAMPLE_CONTROLLER,
            "steps": 5,
            "initial_altitude_m": 0.15,
            "run_async": False,
        }
        run_resp = self.client.post("/experiments/run", json=payload)
        exp_id = run_resp.json()["id"]

        cr_resp = self.client.get(f"/experiments/{exp_id}/court-record")
        record = cr_resp.json()
        record["controller"]["source_code"] = "invalid source code"

        verify_resp = self.client.post("/court-records/verify", json=record)
        self.assertEqual(verify_resp.status_code, 200)
        verify_data = verify_resp.json()
        self.assertFalse(verify_data["verified"])
        self.assertFalse(verify_data["controller_hash_matched"])
        self.assertGreater(len(verify_data["errors"]), 0)

    def test_post_court_record_verify_empty_payload_fails(self):
        verify_resp = self.client.post("/court-records/verify", json={})
        self.assertEqual(verify_resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()

"""Tests for Dómnir FastAPI service, state machine, and orchestration engine."""

import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from domnir.api.app import app, orchestrator
from domnir.api.jobs import (
    ALLOWED_TRANSITIONS,
    ExperimentJob,
    JobOrchestrator,
    StateTransitionError,
)
from domnir.api.models import ExperimentState, RunExperimentRequest
from domnir.inference.vultr import SUPPORTED_MODELS, InferenceResponse
from domnir.spec import FlightSpec, GeneratedController

SAMPLE_CONTROLLER_SOURCE = """
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


class HealthAndReadinessTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], "domnir-api")
        self.assertEqual(data["version"], "0.1.0")
        self.assertIn("timestamp", data)

    def test_ready_endpoint(self):
        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["model_loaded"])
        self.assertIn("glm-5.3-flash", data["supported_models"])
        self.assertIn("qwen3.8-flash-next", data["supported_models"])
        self.assertIn("deepseek-v4.1-flash-1017", data["supported_models"])


class ModelCatalogTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_models_endpoint_exposes_the_three_options(self):
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["default_model"], "glm-5.3-flash")

        model_ids = [m["id"] for m in data["models"]]
        self.assertIn("glm-5.3-flash", model_ids)
        self.assertIn("qwen3.8-flash-next", model_ids)
        self.assertIn("deepseek-v4.1-flash-1017", model_ids)

        families = {m["id"]: m["family"] for m in data["models"]}
        self.assertEqual(families["glm-5.3-flash"], "glm")
        self.assertEqual(families["qwen3.8-flash-next"], "qwen")
        self.assertEqual(families["deepseek-v4.1-flash-1017"], "deepseek")

        for m in data["models"]:
            self.assertEqual(m["provider"], "vultr")
            self.assertEqual(m["reasoning_effort"], "minimal")
            self.assertTrue(len(m["name"]) > 0)
            self.assertTrue(len(m["description"]) > 0)


class SpecValidationEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_valid_spec_accepted(self):
        payload = {
            "spec": {
                "target_altitude_m": 0.1,
                "altitude_tolerance_m": 0.05,
                "min_allowed_altitude_m": 0.05,
                "max_allowed_altitude_m": 1.0,
                "mission_duration_s": 0.4,
                "dt_s": 0.002,
                "disturbance_force_z_min": -0.05,
                "disturbance_force_z_max": 0.05,
            }
        }
        response = self.client.post("/specs/validate", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["step_budget"], 200)

    def test_invalid_spec_rejected(self):
        payload = {
            "spec": {
                "target_altitude_m": 1.5,
                "min_allowed_altitude_m": 0.05,
                "max_allowed_altitude_m": 1.0,
            }
        }
        response = self.client.post("/specs/validate", json=payload)
        self.assertEqual(response.status_code, 422)


class ControllerGenerationEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_unsupported_model_rejected(self):
        payload = {
            "spec": {
                "target_altitude_m": 0.1,
                "mission_duration_s": 0.4,
            },
            "model": "unsupported-model-v1",
        }
        response = self.client.post("/controllers/generate", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("not in supported options", response.json()["detail"])

    @patch("domnir.inference.vultr.VultrInferenceClient.chat_completion")
    def test_generate_controller_with_each_supported_model(self, mock_chat):
        spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.4)
        for model_id in ("glm-5.3-flash", "qwen3.8-flash-next", "deepseek-v4.1-flash-1017"):
            mock_chat.return_value = InferenceResponse(
                content=f"```python\n{SAMPLE_CONTROLLER_SOURCE}\n```",
                model=model_id,
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                finish_reason="stop",
            )
            payload = {
                "spec": spec.model_dump(),
                "model": model_id,
            }
            response = self.client.post("/controllers/generate", json=payload)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["model_id"], model_id)
            self.assertIn("observe", data["controller"]["source_code"])

    @patch("domnir.inference.vultr.VultrInferenceClient.chat_completion")
    def test_generate_controller_with_family_aliases(self, mock_chat):
        spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.4)
        alias_to_model = {
            "glm": "glm-5.3-flash",
            "qwen": "qwen3.8-flash-next",
            "deepseek": "deepseek-v4.1-flash-1017",
        }
        for alias, expected_model in alias_to_model.items():
            mock_chat.return_value = InferenceResponse(
                content=f"```python\n{SAMPLE_CONTROLLER_SOURCE}\n```",
                model=expected_model,
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                finish_reason="stop",
            )
            payload = {
                "spec": spec.model_dump(),
                "model": alias,
            }
            response = self.client.post("/controllers/generate", json=payload)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["model_id"], expected_model)
            self.assertIn("observe", data["controller"]["source_code"])

    @patch("domnir.inference.vultr.VultrInferenceClient.chat_completion")
    def test_generate_controller_with_reasoning_effort_levels(self, mock_chat):
        spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.4)
        mock_chat.return_value = InferenceResponse(
            content=f"```python\n{SAMPLE_CONTROLLER_SOURCE}\n```",
            model="glm-5.3-flash",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            finish_reason="stop",
        )
        for level in ("minimal", "low", "medium", "high"):
            payload = {
                "spec": spec.model_dump(),
                "model": "glm-5.3-flash",
                "reasoning_effort": level,
            }
            response = self.client.post("/controllers/generate", json=payload)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["reasoning_effort"], level)
            self.assertIn("observe", data["controller"]["source_code"])
            # Verify chat_completion was invoked with reasoning_effort
            self.assertEqual(mock_chat.call_args.kwargs.get("reasoning_effort"), level)

    def test_generate_controller_with_invalid_reasoning_effort_rejected(self):
        spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.4)
        payload = {
            "spec": spec.model_dump(),
            "model": "glm-5.3-flash",
            "reasoning_effort": "extreme",
        }
        response = self.client.post("/controllers/generate", json=payload)
        self.assertEqual(response.status_code, 422)


class ExperimentWorkflowTests(unittest.TestCase):
    def setUp(self):
        import os
        os.environ["DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK"] = "1"
        self.client = TestClient(app)

    def test_production_fails_closed_when_microvm_unavailable(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK": ""}):
            with patch("domnir.api.jobs.is_microvm_available", return_value=False):
                spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.1)
                ctrl = GeneratedController.from_source(SAMPLE_CONTROLLER_SOURCE, model_id="glm-5.3-flash")
                payload = {
                    "spec": spec.model_dump(),
                    "controller": ctrl.model_dump(),
                    "steps": 10,
                    "run_async": False,
                }
                response = self.client.post("/experiments/run", json=payload)
                self.assertEqual(response.status_code, 200)
                summary = response.json()
                self.assertEqual(summary["state"], "FAILED")
                self.assertIn("BLOCKED: ISOLATION_UNAVAILABLE", summary["error_message"])

    def test_run_experiment_synchronous_success_nominal(self):
        spec = FlightSpec(
            target_altitude_m=0.1,
            altitude_tolerance_m=0.08,
            min_allowed_altitude_m=0.05,
            max_allowed_altitude_m=0.5,
            mission_duration_s=0.2,
        )
        ctrl = GeneratedController.from_source(SAMPLE_CONTROLLER_SOURCE, model_id="glm-5.3-flash")
        payload = {
            "spec": spec.model_dump(),
            "controller": ctrl.model_dump(),
            "initial_altitude_m": 0.15,
            "vertical_disturbance_n": 0.0,
            "steps": 100,
            "run_async": False,
        }
        response = self.client.post("/experiments/run", json=payload)
        self.assertEqual(response.status_code, 200)
        summary = response.json()
        self.assertEqual(summary["state"], "COMPLETED")
        self.assertEqual(summary["verdict"], "NOT_FALSIFIED")
        self.assertTrue(summary["replay_matched"])
        self.assertLess(summary["replay_max_abs_difference"], 1e-12)
        self.assertTrue(summary["cleanup_succeeded"])

        # Fetch detail
        exp_id = summary["id"]
        detail_resp = self.client.get(f"/experiments/{exp_id}")
        self.assertEqual(detail_resp.status_code, 200)
        detail = detail_resp.json()
        self.assertEqual(detail["id"], exp_id)
        self.assertGreater(detail["telemetry_sample_count"], 0)
        states = [t["to_state"] for t in detail["state_history"]]
        self.assertEqual(
            states,
            ["CREATED", "SPEC_APPROVED", "CONTROLLER_VALIDATED", "QUEUED", "RUNNING", "COMPLETED"],
        )

        # Fetch artifacts
        art_resp = self.client.get(f"/experiments/{exp_id}/artifacts")
        self.assertEqual(art_resp.status_code, 200)
        artifacts = art_resp.json()
        self.assertIsNotNone(artifacts["court_record"])
        self.assertEqual(artifacts["court_record"]["verdict"], "NOT_FALSIFIED")
        self.assertGreater(len(artifacts["trajectory"]), 0)
        self.assertGreater(len(artifacts["event_log"]), 0)

    def test_run_experiment_adversarial_counterexample_falsifies(self):
        spec = FlightSpec(
            target_altitude_m=0.1,
            altitude_tolerance_m=0.005,
            min_allowed_altitude_m=0.05,
            max_allowed_altitude_m=0.5,
            mission_duration_s=0.2,
        )
        ctrl = GeneratedController.from_source(SAMPLE_CONTROLLER_SOURCE, model_id="glm-5.3-flash")
        payload = {
            "spec": spec.model_dump(),
            "controller": ctrl.model_dump(),
            "initial_altitude_m": 0.15,
            "vertical_disturbance_n": -0.04,
            "steps": 100,
            "run_async": False,
        }
        response = self.client.post("/experiments/run", json=payload)
        self.assertEqual(response.status_code, 200)
        summary = response.json()
        self.assertEqual(summary["state"], "COMPLETED")
        self.assertEqual(summary["verdict"], "FALSIFIED")
        self.assertTrue(summary["cleanup_succeeded"])

    def test_run_experiment_async_enqueues(self):
        spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.2)
        ctrl = GeneratedController.from_source(SAMPLE_CONTROLLER_SOURCE, model_id="glm-5.3-flash")
        payload = {
            "spec": spec.model_dump(),
            "controller": ctrl.model_dump(),
            "initial_altitude_m": 0.15,
            "steps": 50,
            "run_async": True,
        }
        response = self.client.post("/experiments/run", json=payload)
        self.assertEqual(response.status_code, 200)
        summary = response.json()
        self.assertIn(summary["state"], ("CREATED", "QUEUED", "RUNNING", "COMPLETED"))

    def test_not_found_handlers(self):
        resp1 = self.client.get("/experiments/missing-uuid-1234")
        self.assertEqual(resp1.status_code, 404)

        resp2 = self.client.get("/experiments/missing-uuid-1234/artifacts")
        self.assertEqual(resp2.status_code, 404)

    def test_invalid_controller_code_transitions_to_failed(self):
        spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.2)
        payload = {
            "spec": spec.model_dump(),
            "controller_source": "invalid python syntax [[",
            "run_async": False,
        }
        response = self.client.post("/experiments/run", json=payload)
        self.assertEqual(response.status_code, 200)
        summary = response.json()
        self.assertEqual(summary["state"], "FAILED")
        self.assertEqual(summary["verdict"], "FAILED")
        self.assertTrue(summary["cleanup_succeeded"])

    def test_zero_thrust_controller_falsifies(self):
        spec = FlightSpec(
            target_altitude_m=0.1,
            min_allowed_altitude_m=0.05,
            max_allowed_altitude_m=0.5,
            mission_duration_s=0.2,
        )
        zero_src = (
            "def observe(obs):\n"
            "    return {'schema_version': '1.0', 'trial_id': obs['trial_id'], "
            "'step_index': obs['step_index'], 'thrust': 0.0, 'moment_x': 0.0, "
            "'moment_y': 0.0, 'moment_z': 0.0}\n"
        )
        ctrl = GeneratedController.from_source(zero_src, model_id="glm-5.3-flash")
        payload = {
            "spec": spec.model_dump(),
            "controller": ctrl.model_dump(),
            "initial_altitude_m": 0.15,
            "steps": 100,
            "run_async": False,
        }
        response = self.client.post("/experiments/run", json=payload)
        self.assertEqual(response.status_code, 200)
        summary = response.json()
        self.assertEqual(summary["state"], "COMPLETED")
        self.assertEqual(summary["verdict"], "FALSIFIED")
        self.assertLess(summary["minimum_altitude_m"], 0.05)
        self.assertTrue(summary["cleanup_succeeded"])

    def test_runtime_error_in_observe_transitions_to_failed(self):
        spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.2)
        crash_src = (
            "def observe(obs):\n"
            "    raise RuntimeError('simulated controller crash')\n"
        )
        ctrl = GeneratedController.from_source(crash_src, model_id="glm-5.3-flash")
        payload = {
            "spec": spec.model_dump(),
            "controller": ctrl.model_dump(),
            "initial_altitude_m": 0.15,
            "steps": 50,
            "run_async": False,
        }
        response = self.client.post("/experiments/run", json=payload)
        self.assertEqual(response.status_code, 200)
        summary = response.json()
        self.assertEqual(summary["state"], "FAILED")
        self.assertEqual(summary["verdict"], "FAILED")
        self.assertTrue(
            any(
                phrase in summary["error_message"]
                for phrase in ("simulated controller crash", "Guest output closed")
            )
        )
        self.assertTrue(summary["cleanup_succeeded"])

    def test_out_of_bounds_action_transitions_to_failed(self):
        spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.2)
        oob_src = (
            "def observe(obs):\n"
            "    return {'schema_version': '1.0', 'trial_id': obs['trial_id'], "
            "'step_index': obs['step_index'], 'thrust': 999.0, 'moment_x': 0.0, "
            "'moment_y': 0.0, 'moment_z': 0.0}\n"
        )
        ctrl = GeneratedController.from_source(oob_src, model_id="glm-5.3-flash")
        payload = {
            "spec": spec.model_dump(),
            "controller": ctrl.model_dump(),
            "initial_altitude_m": 0.15,
            "steps": 50,
            "run_async": False,
        }
        response = self.client.post("/experiments/run", json=payload)
        self.assertEqual(response.status_code, 200)
        summary = response.json()
        self.assertEqual(summary["state"], "FAILED")
        self.assertEqual(summary["verdict"], "FAILED")
        self.assertIn("permitted range", summary["error_message"])
        self.assertTrue(summary["cleanup_succeeded"])

    def test_replay_divergence_leads_to_inconclusive(self):
        import mujoco
        spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.2)
        ctrl = GeneratedController.from_source(SAMPLE_CONTROLLER_SOURCE, model_id="glm-5.3-flash")
        payload = {
            "spec": spec.model_dump(),
            "controller": ctrl.model_dump(),
            "initial_altitude_m": 0.15,
            "steps": 20,
            "run_async": False,
        }
        real_step = mujoco.mj_step
        counter = [0]

        def perturb_during_replay(m, d):
            real_step(m, d)
            counter[0] += 1
            if counter[0] > 20:
                d.qpos[2] += 0.05

        with patch("mujoco.mj_step", side_effect=perturb_during_replay):
            response = self.client.post("/experiments/run", json=payload)

        self.assertEqual(response.status_code, 200)
        summary = response.json()
        self.assertEqual(summary["state"], "INCONCLUSIVE")
        self.assertEqual(summary["verdict"], "INVALID")
        self.assertFalse(summary["replay_matched"])
        self.assertTrue(summary["cleanup_succeeded"])


class StateMachineUnitTests(unittest.TestCase):
    def test_state_machine_illegal_transition_raises(self):
        spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.2)
        job = ExperimentJob("test-job-001", spec)
        self.assertEqual(job.state, ExperimentState.CREATED)

        # CREATED cannot jump directly to COMPLETED
        with self.assertRaises(StateTransitionError):
            job.transition_to(ExperimentState.COMPLETED)

        # Valid transition to SPEC_APPROVED
        job.transition_to(ExperimentState.SPEC_APPROVED)
        self.assertEqual(job.state, ExperimentState.SPEC_APPROVED)

        # SPEC_APPROVED cannot jump directly to RUNNING
        with self.assertRaises(StateTransitionError):
            job.transition_to(ExperimentState.RUNNING)

        # Terminal state cannot transition anywhere
        job.state = ExperimentState.COMPLETED
        with self.assertRaises(StateTransitionError):
            job.transition_to(ExperimentState.RUNNING)

    def test_job_queue_bounding(self):
        orchestrator = JobOrchestrator(max_queue_size=2)
        spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.2)
        req = RunExperimentRequest(spec=spec)

        j1 = orchestrator.create_job(req)
        j2 = orchestrator.create_job(req)
        with self.assertRaises(RuntimeError):
            orchestrator.create_job(req)

        self.assertIsNotNone(orchestrator.get_job(j1.id))
        self.assertIsNotNone(orchestrator.get_job(j2.id))

    def test_queue_bounding_counts_intermediate_states(self):
        orchestrator = JobOrchestrator(max_queue_size=2)
        spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.2)
        req = RunExperimentRequest(spec=spec)

        j1 = orchestrator.create_job(req)
        j1.transition_to(ExperimentState.SPEC_APPROVED)

        j2 = orchestrator.create_job(req)
        j2.transition_to(ExperimentState.SPEC_APPROVED)
        j2.transition_to(ExperimentState.CONTROLLER_VALIDATED)

        with self.assertRaises(RuntimeError):
            orchestrator.create_job(req)


if __name__ == "__main__":
    unittest.main()

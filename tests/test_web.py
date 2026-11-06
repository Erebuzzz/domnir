"""Unit and integration tests for Dómnir Web UI delivery and client assets."""

import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from domnir.api.app import app, WEB_DIR


class WebAppDeliveryTests(unittest.TestCase):
    def setUp(self):
        import os
        os.environ["DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK"] = "1"
        self.client = TestClient(app)

    def test_web_directory_exists(self):
        self.assertTrue(WEB_DIR.is_dir(), f"Web directory does not exist: {WEB_DIR}")
        self.assertTrue((WEB_DIR / "index.html").is_file())
        self.assertTrue((WEB_DIR / "styles.css").is_file())
        self.assertTrue((WEB_DIR / "app.js").is_file())
        self.assertTrue((WEB_DIR / "favicon.svg").is_file())

    def test_root_route_serves_html(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        text = response.text
        self.assertIn("DÓMNIR", text)
        self.assertIn("BLAST RADIUS ZERO", text)
        self.assertIn("Mission Configuration", text)
        self.assertIn("Court Record Verifier", text)
        self.assertIn("Trust Architecture", text)

    def test_direct_index_html_route(self):
        response = self.client.get("/index.html")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertIn("DÓMNIR", response.text)

    def test_favicon_delivery(self):
        response = self.client.get("/favicon.svg")
        self.assertEqual(response.status_code, 200)
        content_type = response.headers.get("content-type", "")
        self.assertTrue("svg" in content_type or "xml" in content_type)
        self.assertIn("<svg", response.text)

    def test_static_css_delivery(self):
        response = self.client.get("/styles.css")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response.headers.get("content-type", ""))
        self.assertIn("--bg-core", response.text)
        self.assertIn("altitude-svg-chart", response.text)

    def test_static_js_delivery(self):
        response = self.client.get("/app.js")
        self.assertEqual(response.status_code, 200)
        content_type = response.headers.get("content-type", "")
        self.assertTrue(
            "javascript" in content_type or "text/plain" in content_type,
            f"Unexpected content type for js: {content_type}",
        )
        self.assertIn("checkHealthAndReadiness", response.text)
        self.assertIn("renderAltitudeChart", response.text)
        self.assertIn("verifyCourtRecord", response.text)

    def test_api_routes_priority_over_static(self):
        # API endpoints must not be masked by static files mount
        health_res = self.client.get("/health")
        self.assertEqual(health_res.status_code, 200)
        health_data = health_res.json()
        self.assertEqual(health_data["status"], "ok")

        models_res = self.client.get("/models")
        self.assertEqual(models_res.status_code, 200)
        models_data = models_res.json()
        self.assertIn("models", models_data)
        self.assertEqual(models_data["default_model"], "glm-5.3-flash")

        ready_res = self.client.get("/ready")
        self.assertEqual(ready_res.status_code, 200)
        self.assertIn("ready", ready_res.json())

    def test_nonexistent_asset_returns_404(self):
        response = self.client.get("/nonexistent-file-xyz.dat")
        self.assertEqual(response.status_code, 404)

    def test_no_secrets_in_client_assets(self):
        sensitive_patterns = [
            "VULTR_INFERENCE_API_KEY",
            "sk-",
            "Bearer ",
            "password=",
            "api_key",
            "PRIVATE KEY",
        ]
        for asset_name in ["index.html", "styles.css", "app.js"]:
            asset_path = WEB_DIR / asset_name
            content = asset_path.read_text(encoding="utf-8")
            for pattern in sensitive_patterns:
                self.assertNotIn(
                    pattern,
                    content,
                    f"Sensitive pattern '{pattern}' found in {asset_name}",
                )

    def test_no_em_dashes_in_web_assets(self):
        for asset_path in WEB_DIR.glob("*.*"):
            content = asset_path.read_text(encoding="utf-8")
            self.assertNotIn(
                "\u2014",
                content,
                f"Em dash found in {asset_path.name}",
            )

    def test_all_m4_features_present_in_markup(self):
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")

        # Feature 1: Mission Spec & Bounds
        self.assertIn("target_altitude_m", content)
        self.assertIn("altitude_tolerance_m", content)
        self.assertIn("min_allowed_altitude_m", content)
        self.assertIn("max_allowed_altitude_m", content)
        self.assertIn("mission_duration_s", content)
        self.assertIn("disturbance_force_z_min", content)
        self.assertIn("disturbance_force_z_max", content)
        self.assertIn("validateSpecBtn", content)

        # Feature 2: Multi-Model Selection & Reasoning Effort
        self.assertIn("glm-5.3-flash", content)
        self.assertIn("qwen3.8-flash-next", content)
        self.assertIn("deepseek-v4.1-flash-1017", content)
        self.assertIn("reasoningEffortGroup", content)
        self.assertIn("reasoning-pill", content)

        # Feature 3: Controller Generation & Preview
        self.assertIn("generateControllerBtn", content)
        self.assertIn("controllerSource", content)
        self.assertIn("controllerHash", content)
        self.assertIn("controllerAstBadge", content)

        # Feature 4: Execution & Altitude Trace Chart
        self.assertIn("runExperimentBtn", content)
        self.assertIn("stateTracker", content)
        self.assertIn("altitudeSvgChart", content)

        # Feature 5: Replay Determinism & Honest Verdicts
        self.assertIn("replayDiffValue", content)
        self.assertIn("1.00e-12 m", content)
        self.assertIn("verdictFlight", content)
        self.assertIn("MANDATORY ADJUDICATION DISCLOSURE", content)
        self.assertIn("INCONCLUSIVE regarding universal safety", content)

        # Feature 6: Court Record Export & Independent Verifier
        self.assertIn("downloadCourtRecordBtn", content)
        self.assertIn("dropZone", content)
        self.assertIn("submitVerifyBtn", content)
        self.assertIn("verifyResultsCard", content)

        # Robustness & Sensory feedback additions
        self.assertIn("executionErrorBanner", content)
        self.assertIn("toastContainer", content)
        self.assertIn("favicon.svg", content)

    def test_accessibility_and_semantic_html(self):
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('<!DOCTYPE html>', content)
        self.assertIn('<html lang="en">', content)
        self.assertIn('<meta name="viewport"', content)
        self.assertIn('<meta name="description"', content)
        self.assertIn('<main class="main-content">', content)
        self.assertIn('<header class="app-header">', content)
        self.assertIn('<footer class="app-footer">', content)
        self.assertIn('aria-label="Main Navigation"', content)

        # Check label 'for' attributes matching input 'id's
        for field_id in [
            "targetAltitude",
            "altitudeTolerance",
            "minAltitude",
            "maxAltitude",
            "missionDuration",
            "distZMin",
            "distZMax",
        ]:
            self.assertIn(f'for="{field_id}"', content)
            self.assertIn(f'id="{field_id}"', content)

    def test_containment_audit_ui_elements(self):
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-tab="tab-containment"', html)
        self.assertIn('id="tab-containment"', html)
        self.assertIn("CAP-HOST-001", html)
        self.assertIn("NET-EGRESS-001", html)
        self.assertIn("RES-TIME-001", html)
        self.assertIn("RES-MEM-001", html)
        self.assertIn("CLEANUP-100", html)
        self.assertIn("refreshContainmentBtn", html)
        self.assertIn("runContainmentBtn", html)
        self.assertIn("fixtureBadgeCleanup", html)
        self.assertIn("fixtureAuditCleanup", html)
        self.assertIn("fixtureCleanupMem", html)
        self.assertIn("fixtureOrphanedVms", html)
        self.assertIn("fixturePostRunTable", html)

        js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("fetchContainmentStatus", js)
        self.assertIn("runContainmentSuite", js)
        self.assertIn("/containment/status", js)
        self.assertIn("/containment/run", js)
        self.assertIn("fixtureBadgeCleanup", js)
        self.assertIn("fixtureAuditCleanup", js)
        self.assertIn("fixtureCleanupMem", js)

        css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".containment-container", css)
        self.assertIn(".fixture-card", css)

    def test_full_web_client_api_workflow(self):
        # 1. Spec validation
        spec_payload = {
            "spec": {
                "target_altitude_m": 0.10,
                "altitude_tolerance_m": 0.05,
                "min_allowed_altitude_m": 0.05,
                "max_allowed_altitude_m": 1.00,
                "mission_duration_s": 0.04,  # small duration for rapid test
                "dt_s": 0.002,
                "disturbance_force_z_min": -0.05,
                "disturbance_force_z_max": 0.05,
            }
        }
        val_res = self.client.post("/specs/validate", json=spec_payload)
        self.assertEqual(val_res.status_code, 200)
        self.assertTrue(val_res.json()["valid"])

        # 2. Controller source
        sample_source = (
            "def observe(obs):\n"
            "    z = obs['position_m'][2]\n"
            "    vz = obs['velocity_mps'][2]\n"
            "    thrust = max(0.0, min(0.35, 0.26487 + 0.15 * (0.1 - z) - 0.08 * vz))\n"
            "    return {\n"
            "        'schema_version': '1.0',\n"
            "        'trial_id': obs['trial_id'],\n"
            "        'step_index': obs['step_index'],\n"
            "        'thrust': float(thrust),\n"
            "        'moment_x': 0.0,\n"
            "        'moment_y': 0.0,\n"
            "        'moment_z': 0.0,\n"
            "    }\n"
        )

        # 3. Run trial
        run_payload = {
            "spec": spec_payload["spec"],
            "controller_source": sample_source,
            "model": "glm-5.3-flash",
            "initial_altitude_m": 0.15,
            "vertical_disturbance_n": 0.0,
            "seed": 42,
            "run_async": False,
        }
        run_res = self.client.post("/experiments/run", json=run_payload)
        self.assertEqual(run_res.status_code, 200)
        summary = run_res.json()
        exp_id = summary["id"]
        self.assertEqual(summary["state"], "COMPLETED")
        self.assertIn(summary["verdict"], ["NOT_FALSIFIED", "FALSIFIED"])

        # 4. Fetch artifacts (trajectory & court record)
        art_res = self.client.get(f"/experiments/{exp_id}/artifacts")
        self.assertEqual(art_res.status_code, 200)
        artifacts = art_res.json()
        self.assertGreater(len(artifacts["trajectory"]), 0)
        self.assertIsNotNone(artifacts["court_record"])

        # 5. Fetch court record directly
        cr_res = self.client.get(f"/experiments/{exp_id}/court-record")
        self.assertEqual(cr_res.status_code, 200)
        court_record = cr_res.json()
        self.assertTrue(court_record["record_id"].startswith("cr-"))
        self.assertEqual(court_record["experiment_id"], exp_id)

        # 6. Verify court record independently
        verify_res = self.client.post("/court-records/verify", json={"court_record": court_record})
        self.assertEqual(verify_res.status_code, 200)
        verify_data = verify_res.json()
        self.assertTrue(verify_data["verified"])
        self.assertTrue(verify_data["controller_hash_matched"])
        self.assertTrue(verify_data["trajectory_hash_matched"])
        self.assertTrue(verify_data["model_hashes_matched"])
        self.assertTrue(verify_data["event_chain_verified"])
        self.assertLessEqual(verify_data["replay_max_abs_difference"], 1e-12)

    def test_failing_experiment_web_workflow(self):
        broken_source = (
            "def observe(obs):\n"
            "    raise RuntimeError('Simulated guest exception')\n"
        )
        payload = {
            "spec": {
                "target_altitude_m": 0.10,
                "altitude_tolerance_m": 0.05,
                "min_allowed_altitude_m": 0.05,
                "max_allowed_altitude_m": 1.00,
                "mission_duration_s": 0.04,
                "dt_s": 0.002,
                "disturbance_force_z_min": -0.05,
                "disturbance_force_z_max": 0.05,
            },
            "controller_source": broken_source,
            "model": "glm-5.3-flash",
            "initial_altitude_m": 0.15,
            "vertical_disturbance_n": 0.0,
            "seed": 42,
            "run_async": False,
        }
        res = self.client.post("/experiments/run", json=payload)
        self.assertEqual(res.status_code, 200)
        summary = res.json()
        self.assertEqual(summary["state"], "FAILED")
        self.assertEqual(summary["verdict"], "FAILED")
        self.assertIsNotNone(summary["error_message"])

        detail_res = self.client.get(f"/experiments/{summary['id']}")
        self.assertEqual(detail_res.status_code, 200)
        detail = detail_res.json()
        self.assertEqual(detail["state"], "FAILED")
        self.assertTrue(
            any(
                phrase in detail["error_message"]
                for phrase in ("Simulated guest exception", "Guest output closed")
            )
        )
        self.assertTrue(any(rec["to_state"] == "FAILED" for rec in detail["state_history"]))

    def test_falsified_adversarial_counterexample_web_workflow(self):
        zero_thrust_source = (
            "def observe(obs):\n"
            "    return {\n"
            "        'schema_version': '1.0',\n"
            "        'trial_id': obs['trial_id'],\n"
            "        'step_index': obs['step_index'],\n"
            "        'thrust': 0.0,\n"
            "        'moment_x': 0.0,\n"
            "        'moment_y': 0.0,\n"
            "        'moment_z': 0.0,\n"
            "    }\n"
        )
        payload = {
            "spec": {
                "target_altitude_m": 0.20,
                "altitude_tolerance_m": 0.05,
                "min_allowed_altitude_m": 0.10,
                "max_allowed_altitude_m": 1.00,
                "mission_duration_s": 0.20,
                "dt_s": 0.002,
                "disturbance_force_z_min": -0.05,
                "disturbance_force_z_max": 0.05,
            },
            "controller_source": zero_thrust_source,
            "model": "glm-5.3-flash",
            "initial_altitude_m": 0.15,
            "vertical_disturbance_n": 0.0,
            "seed": 42,
            "run_async": False,
        }
        res = self.client.post("/experiments/run", json=payload)
        self.assertEqual(res.status_code, 200)
        summary = res.json()
        self.assertEqual(summary["state"], "COMPLETED")
        self.assertEqual(summary["verdict"], "FALSIFIED")
        self.assertLess(summary["minimum_altitude_m"], 0.10)

    def test_tampered_court_record_rejected_by_verifier(self):
        spec = {
            "target_altitude_m": 0.10,
            "altitude_tolerance_m": 0.05,
            "min_allowed_altitude_m": 0.05,
            "max_allowed_altitude_m": 1.00,
            "mission_duration_s": 0.04,
            "dt_s": 0.002,
            "disturbance_force_z_min": -0.05,
            "disturbance_force_z_max": 0.05,
        }
        hover_source = (
            "def observe(obs):\n"
            "    z = obs['position_m'][2]\n"
            "    return {\n"
            "        'schema_version': '1.0',\n"
            "        'trial_id': obs['trial_id'],\n"
            "        'step_index': obs['step_index'],\n"
            "        'thrust': 0.26487,\n"
            "        'moment_x': 0.0,\n"
            "        'moment_y': 0.0,\n"
            "        'moment_z': 0.0,\n"
            "    }\n"
        )
        res = self.client.post("/experiments/run", json={
            "spec": spec,
            "controller_source": hover_source,
            "initial_altitude_m": 0.10,
            "run_async": False,
        })
        self.assertEqual(res.status_code, 200)
        exp_id = res.json()["id"]

        cr_res = self.client.get(f"/experiments/{exp_id}/court-record")
        self.assertEqual(cr_res.status_code, 200)
        record = cr_res.json()

        # Tamper trajectory data
        record["trajectory"]["position_m"][0][2] = 99.999

        # Independent verifier must reject
        verify_res = self.client.post("/court-records/verify", json={"court_record": record})
        self.assertEqual(verify_res.status_code, 200)
        result = verify_res.json()
        self.assertFalse(result["verified"])
        self.assertFalse(result["trajectory_hash_matched"])
        self.assertGreater(len(result["errors"]), 0)


if __name__ == "__main__":
    unittest.main()


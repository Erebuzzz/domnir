"""Unit tests and mock suite for Vultr Serverless Inference integration."""

import os
import unittest
from unittest.mock import MagicMock, patch
import httpx

from domnir.inference.vultr import (
    AuthenticationError,
    InferenceError,
    ModelMismatchError,
    ModelNotFoundError,
    RateLimitError,
    VultrInferenceClient,
    _redact_key,
    clean_python_code,
)
from domnir.spec import FlightSpec


class VultrInferenceUnitTests(unittest.TestCase):
    def test_key_redaction(self):
        self.assertEqual(_redact_key(None), "<none>")
        self.assertEqual(_redact_key(""), "<none>")
        self.assertEqual(_redact_key("short"), "****")
        self.assertEqual(_redact_key("DKXIAZPBCPWTK6FNPGJUANG3NJTVWL2EYWHA"), "DKXI...YWHA")

    def test_client_repr_does_not_leak_key(self):
        secret = "DKXIAZPBCPWTK6FNPGJUANG3NJTVWL2EYWHA"
        client = VultrInferenceClient(api_key=secret)
        repr_str = repr(client)
        self.assertNotIn(secret, repr_str)
        self.assertIn("DKXI...YWHA", repr_str)

    def test_clean_python_code_strips_fences(self):
        fenced = "```python\ndef observe(observation):\n    return {}\n```"
        self.assertEqual(clean_python_code(fenced), "def observe(observation):\n    return {}")

        bare = "def observe(observation):\n    return {}"
        self.assertEqual(clean_python_code(bare), bare)

    @patch("httpx.Client.get")
    def test_list_models_success_and_caching(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "glm-5.3-flash"},
                {"id": "qwen3.8-flash-next"},
            ]
        }
        mock_get.return_value = mock_response

        client = VultrInferenceClient(api_key="mock-key")
        models = client.list_models()
        self.assertEqual(models, ["glm-5.3-flash", "qwen3.8-flash-next"])
        self.assertEqual(mock_get.call_count, 1)

        # Second call uses cache
        cached = client.list_models()
        self.assertEqual(cached, ["glm-5.3-flash", "qwen3.8-flash-next"])
        self.assertEqual(mock_get.call_count, 1)

    @patch("httpx.Client.get")
    def test_validate_model_id_raises_for_missing_model(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "glm-5.3-flash"}]}
        mock_get.return_value = mock_response

        client = VultrInferenceClient(api_key="mock-key")
        with self.assertRaises(ModelNotFoundError):
            client.validate_model_id("non-existent-model")

    @patch("httpx.Client.post")
    @patch("httpx.Client.get")
    def test_chat_completion_detects_model_mismatch(self, mock_get, mock_post):
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.return_value = {"data": [{"id": "glm-5.3-flash"}]}
        mock_get.return_value = mock_get_resp

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "model": "unexpected-fallback-model",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        mock_post.return_value = mock_post_resp

        client = VultrInferenceClient(api_key="mock-key")
        with self.assertRaises(ModelMismatchError):
            client.chat_completion([{"role": "user", "content": "hi"}], model="glm-5.3-flash")

    @patch("httpx.Client.post")
    @patch("httpx.Client.get")
    def test_chat_completion_handles_401(self, mock_get, mock_post):
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.return_value = {"data": [{"id": "glm-5.3-flash"}]}
        mock_get.return_value = mock_get_resp

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 401
        mock_post.return_value = mock_post_resp

        client = VultrInferenceClient(api_key="bad-key")
        with self.assertRaises(AuthenticationError):
            client.chat_completion([{"role": "user", "content": "hi"}], model="glm-5.3-flash")


class VultrLiveInferenceTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("DOMNIR_RUN_LIVE_INFERENCE") == "1",
        "Requires live Vultr Serverless Inference API key and DOMNIR_RUN_LIVE_INFERENCE=1",
    )
    def test_live_chat_completion_and_controller_generation(self):
        client = VultrInferenceClient()
        models = client.list_models()
        self.assertIn("glm-5.3-flash", models)

        spec = FlightSpec(target_altitude_m=0.1, mission_duration_s=0.4)
        controller = client.generate_controller(spec, model="glm-5.3-flash")

        self.assertIn("observe", controller.source_code)
        self.assertLessEqual(len(controller.source_code.encode("utf-8")), 32768)
        self.assertEqual(controller.model_id, "glm-5.3-flash")

"""Vultr Serverless Inference client and controller generator."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import httpx

from domnir.spec import FlightSpec, GeneratedController

DEFAULT_BASE_URL = "https://api.vultrinference.com/v1"
DEFAULT_MODEL = "glm-5.3-flash"

SUPPORTED_MODELS: dict[str, dict[str, Any]] = {
    "glm-5.3-flash": {
        "id": "glm-5.3-flash",
        "name": "GLM 5.3 Flash",
        "family": "glm",
        "provider": "vultr",
        "description": "General Language Model by Zhipu AI optimized for low-latency reasoning and control.",
        "default": True,
        "reasoning_effort": "minimal",
    },
    "qwen3.8-flash-next": {
        "id": "qwen3.8-flash-next",
        "name": "Qwen 3.8 Flash Next",
        "family": "qwen",
        "provider": "vultr",
        "description": "Alibaba Qwen model optimized for fast code generation and physics understanding.",
        "default": False,
        "reasoning_effort": "minimal",
    },
    "deepseek-v4.1-flash-1017": {
        "id": "deepseek-v4.1-flash-1017",
        "name": "DeepSeek V4.1 Flash 1017",
        "family": "deepseek",
        "provider": "vultr",
        "description": "DeepSeek reasoning model specialized for mathematical and control tasks.",
        "default": False,
        "reasoning_effort": "minimal",
    },
}


def resolve_model_id(model_id: str | None) -> str:
    if not model_id:
        return DEFAULT_MODEL
    normalized = model_id.strip()
    if normalized in SUPPORTED_MODELS:
        return normalized
    lower = normalized.lower()
    alias_map = {
        "glm": "glm-5.3-flash",
        "qwen": "qwen3.8-flash-next",
        "deepseek": "deepseek-v4.1-flash-1017",
    }
    if lower in alias_map:
        return alias_map[lower]
    for key, info in SUPPORTED_MODELS.items():
        if lower == info["family"].lower() or lower == info["name"].lower():
            return key
    raise ModelNotFoundError(
        f"Model '{model_id}' is not in supported options: {list(SUPPORTED_MODELS.keys())}"
    )


class InferenceError(RuntimeError):
    """Base exception for Vultr inference failures."""


class AuthenticationError(InferenceError):
    """API key missing, rejected, or invalid."""


class RateLimitError(InferenceError):
    """Rate limit exceeded on Vultr Serverless Inference."""


class ModelNotFoundError(InferenceError):
    """Requested model ID is not available in the live Vultr catalog."""


class ModelMismatchError(InferenceError):
    """Returned model ID does not match the requested model."""


@dataclass(frozen=True)
class InferenceResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str
    system_fingerprint: str | None = None
    reasoning: str | None = None


def _redact_key(key: str | None) -> str:
    if not key:
        return "<none>"
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def _find_env_key() -> str | None:
    direct = os.environ.get("VULTR_INFERENCE_API_KEY")
    if direct:
        return direct.strip()
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for env_path in candidates:
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("VULTR_INFERENCE_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
            except (OSError, UnicodeDecodeError):
                continue
    return None


def clean_python_code(raw_text: str) -> str:
    text = raw_text.strip()
    match = re.search(r"```(?:python)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.split("\n")
        return "\n".join(lines[1:-1]).strip()
    return text


class VultrInferenceClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key or _find_env_key()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._cached_models: list[str] | None = None
        self._cache_time: float = 0.0

    def __repr__(self) -> str:
        return f"VultrInferenceClient(base_url='{self.base_url}', api_key='{_redact_key(self.api_key)}')"

    def list_models(self, force_refresh: bool = False) -> list[str]:
        now = time.time()
        if not force_refresh and self._cached_models and (now - self._cache_time < 300):
            return self._cached_models

        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.base_url}/models"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(url, headers=headers)
                if response.status_code == 401:
                    raise AuthenticationError("Vultr inference authentication failed: invalid API key")
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as error:
            raise InferenceError(f"Failed to fetch model catalog: HTTP {error.response.status_code}") from error
        except httpx.RequestError as error:
            raise InferenceError(f"Network error while connecting to {self.base_url}") from error

        model_entries = data.get("data", [])
        models = [entry["id"] for entry in model_entries if "id" in entry]
        self._cached_models = models
        self._cache_time = now
        return models

    def is_live_verified(self) -> bool:
        if not self.api_key:
            return False
        if self._cached_models and (time.time() - self._cache_time < 300):
            return True
        try:
            models = self.list_models()
            return bool(models)
        except Exception:
            return False

    def validate_model_id(self, model_id: str) -> None:
        catalog = self.list_models()
        if model_id not in catalog:
            raise ModelNotFoundError(
                f"Model '{model_id}' is not in the live Vultr inference catalog. "
                f"Available: {', '.join(catalog[:5])}..."
            )

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        reasoning_effort: str | None = "minimal",
    ) -> InferenceResponse:
        if not self.api_key:
            raise AuthenticationError("VULTR_INFERENCE_API_KEY is not configured")

        self.validate_model_id(model)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    resp = client.post(url, headers=headers, json=payload)

                if resp.status_code == 401:
                    raise AuthenticationError("Vultr inference rejected API key (HTTP 401)")
                if resp.status_code == 429:
                    if attempt < self.max_retries - 1:
                        time.sleep(2**attempt * 0.5)
                        continue
                    raise RateLimitError("Vultr inference rate limit exceeded (HTTP 429)")
                if resp.status_code >= 500:
                    if attempt < self.max_retries - 1:
                        time.sleep(2**attempt * 0.5)
                        continue
                    raise InferenceError(f"Vultr inference service error (HTTP {resp.status_code})")

                resp.raise_for_status()
                data: dict[str, Any] = resp.json()

                returned_model = data.get("model", "")
                if returned_model != model and not returned_model.startswith(model):
                    raise ModelMismatchError(
                        f"Requested model '{model}', but Vultr returned '{returned_model}'"
                    )

                choice = data["choices"][0]
                message = choice.get("message", {})
                content = message.get("content", "") or ""
                reasoning = message.get("reasoning")
                usage = data.get("usage", {})

                return InferenceResponse(
                    content=content,
                    model=returned_model,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    finish_reason=choice.get("finish_reason", "unknown"),
                    system_fingerprint=data.get("system_fingerprint"),
                    reasoning=reasoning,
                )

            except (httpx.TimeoutException, httpx.NetworkError) as error:
                last_error = error
                if attempt < self.max_retries - 1:
                    time.sleep(2**attempt * 0.5)
                    continue
                raise InferenceError(f"Network error contacting Vultr inference: {error}") from error

        raise InferenceError(f"Inference failed after {self.max_retries} attempts: {last_error}")

    def generate_controller(
        self,
        spec: FlightSpec,
        *,
        model: str = DEFAULT_MODEL,
        prompt_version: str = "v1",
        reasoning_effort: str | None = "minimal",
        max_tokens: int = 4096,
    ) -> GeneratedController:
        system_prompt = (
            "You are an expert autonomous control systems engineer for the Bitcraze Crazyflie 2.0 quadrotor "
            "simulated in MuJoCo. Generate a Python flight controller that meets the user's flight specification. "
            "Your output must contain only pure Python code with no markdown formatting or commentary."
        )

        user_prompt = f"""Target flight specification:
- Target altitude: {spec.target_altitude_m} m
- Altitude tolerance: ±{spec.altitude_tolerance_m} m
- Duration: {spec.mission_duration_s} s ({spec.step_budget} steps at dt={spec.dt_s}s)
- Safety bounds: [{spec.min_allowed_altitude_m}, {spec.max_allowed_altitude_m}] m

Contract requirements:
1. Define a top-level synchronous function: observe(observation)
2. observation has:
   - position_m: [x, y, z] in meters
   - velocity_mps: [vx, vy, vz] in m/s
   - trial_id: string
   - step_index: integer
3. Must return a dict matching the action schema:
   {{
       "schema_version": "1.0",
       "trial_id": observation["trial_id"],
       "step_index": observation["step_index"],
       "thrust": thrust_value,
       "moment_x": 0.0,
       "moment_y": 0.0,
       "moment_z": 0.0,
   }}
4. Physical limits:
   - Hover thrust for Crazyflie 2 is approximately 0.26487 N (mass 0.027 kg * 9.81 m/s^2).
   - thrust must be clamped to [0.0, 0.35] N.
   - moments must be clamped to [-1.0, 1.0].
5. Use proportional-derivative (PD) altitude control to hold {spec.target_altitude_m} m.
Return ONLY valid Python source code defining observe(observation).
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = self.chat_completion(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
            reasoning_effort=reasoning_effort,
        )
        source = clean_python_code(response.content)

        return GeneratedController.from_source(
            source,
            model_id=response.model,
            prompt_version=prompt_version,
        )

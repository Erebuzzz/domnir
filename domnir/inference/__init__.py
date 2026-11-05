"""Vultr Serverless Inference provider package."""

from domnir.inference.vultr import (
    DEFAULT_MODEL,
    SUPPORTED_MODELS,
    AuthenticationError,
    InferenceError,
    ModelMismatchError,
    ModelNotFoundError,
    RateLimitError,
    VultrInferenceClient,
    resolve_model_id,
)

__all__ = [
    "DEFAULT_MODEL",
    "SUPPORTED_MODELS",
    "AuthenticationError",
    "InferenceError",
    "ModelMismatchError",
    "ModelNotFoundError",
    "RateLimitError",
    "VultrInferenceClient",
    "resolve_model_id",
]

"""Flight specification and generated controller schemas."""

from __future__ import annotations

import ast
import hashlib
from datetime import datetime, timezone
from typing import Self
from pydantic import BaseModel, Field, model_validator


class FlightSpec(BaseModel):
    target_altitude_m: float = Field(default=0.1, gt=0.0, le=5.0)
    altitude_tolerance_m: float = Field(default=0.05, gt=0.0, le=1.0)
    min_allowed_altitude_m: float = Field(default=0.05, ge=0.0, le=2.0)
    max_allowed_altitude_m: float = Field(default=1.0, gt=0.05, le=10.0)
    mission_duration_s: float = Field(default=0.4, ge=0.02, le=10.0)
    dt_s: float = Field(default=0.002, frozen=True)
    disturbance_force_z_min: float = Field(default=-0.05, ge=-1.0, le=0.0)
    disturbance_force_z_max: float = Field(default=0.05, ge=0.0, le=1.0)

    @property
    def step_budget(self) -> int:
        return int(round(self.mission_duration_s / self.dt_s))

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.min_allowed_altitude_m >= self.max_allowed_altitude_m:
            raise ValueError("Minimum altitude must be strictly less than maximum altitude")
        if self.target_altitude_m <= self.min_allowed_altitude_m:
            raise ValueError("Target altitude must be above minimum allowed altitude")
        if self.target_altitude_m >= self.max_allowed_altitude_m:
            raise ValueError("Target altitude must be below maximum allowed altitude")
        if self.disturbance_force_z_min > self.disturbance_force_z_max:
            raise ValueError("Minimum disturbance cannot exceed maximum disturbance")
        return self


class GeneratedController(BaseModel):
    source_code: str
    model_id: str
    prompt_version: str = "v1"
    source_sha256: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        raw_bytes = self.source_code.encode("utf-8")
        if not (1 <= len(raw_bytes) <= 32768):
            raise ValueError("Controller source must be between 1 and 32768 bytes")
        if b"\x00" in raw_bytes:
            raise ValueError("Controller source cannot contain null bytes")
        try:
            tree = ast.parse(self.source_code, filename="controller.py")
        except (SyntaxError, ValueError, RecursionError) as error:
            raise ValueError("Controller source is not valid Python") from error

        observe_fn = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "observe":
                observe_fn = node
                break

        if observe_fn is None:
            raise ValueError("Controller must define a synchronous top-level observe function")

        if len(observe_fn.args.args) != 1:
            raise ValueError("The observe function must take exactly one argument: observation")

        computed_hash = hashlib.sha256(raw_bytes).hexdigest()
        if self.source_sha256 != computed_hash:
            raise ValueError(
                f"Source hash mismatch: expected {computed_hash}, got {self.source_sha256}"
            )
        return self

    @classmethod
    def from_source(
        cls,
        source_code: str,
        *,
        model_id: str,
        prompt_version: str = "v1",
    ) -> GeneratedController:
        raw_bytes = source_code.encode("utf-8")
        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        return cls(
            source_code=source_code,
            model_id=model_id,
            prompt_version=prompt_version,
            source_sha256=sha256,
        )

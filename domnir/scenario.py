"""Physical scenario parameters and disturbance schedule engine for flight evaluations."""

from __future__ import annotations

import math
from typing import Any, Sequence
from pydantic import BaseModel, Field


class ScenarioParameter(BaseModel):
    initial_altitude_m: float = Field(default=0.10, gt=0.0, le=5.0)
    disturbance_force_z: float = Field(default=0.0, ge=-2.0, le=2.0)
    pulse_start_s: float = Field(default=0.0, ge=0.0, le=10.0)
    pulse_duration_s: float = Field(default=0.0, ge=0.0, le=10.0)

    def to_vector(self) -> list[float]:
        return [
            self.initial_altitude_m,
            self.disturbance_force_z,
            self.pulse_start_s,
            self.pulse_duration_s,
        ]

    @classmethod
    def from_vector(cls, vec: Sequence[float]) -> ScenarioParameter:
        if len(vec) < 2:
            raise ValueError("Scenario vector requires at least 2 elements: [altitude, force]")
        return cls(
            initial_altitude_m=float(vec[0]),
            disturbance_force_z=float(vec[1]),
            pulse_start_s=float(vec[2]) if len(vec) > 2 else 0.0,
            pulse_duration_s=float(vec[3]) if len(vec) > 3 else 0.0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_altitude_m": self.initial_altitude_m,
            "disturbance_force_z": self.disturbance_force_z,
            "pulse_start_s": self.pulse_start_s,
            "pulse_duration_s": self.pulse_duration_s,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScenarioParameter:
        init_z = float(data.get("initial_altitude_m", 0.10))
        dist_f = float(
            data.get("disturbance_force_z", data.get("vertical_disturbance_n", 0.0))
        )
        p_start = float(data.get("pulse_start_s", 0.0))
        p_dur = float(data.get("pulse_duration_s", 0.0))
        return cls(
            initial_altitude_m=init_z,
            disturbance_force_z=dist_f,
            pulse_start_s=p_start,
            pulse_duration_s=p_dur,
        )


def calculate_applied_disturbance(
    scenario: ScenarioParameter,
    sim_time_s: float,
) -> float:
    """Compute instantaneous vertical disturbance force F_z(t) according to pulse schedule."""
    if not math.isfinite(sim_time_s):
        return 0.0

    force = float(scenario.disturbance_force_z)
    if abs(force) < 1e-12:
        return 0.0

    p_dur = float(scenario.pulse_duration_s)
    p_start = float(scenario.pulse_start_s)

    if p_dur > 0.0:
        p_end = p_start + p_dur
        # Timed pulse window [pulse_start_s, pulse_start_s + pulse_duration_s) with float epsilon
        if (p_start - 1e-9) <= sim_time_s < (p_end - 1e-9):
            return force
        return 0.0

    # Legacy fallback: continuous disturbance when pulse_duration_s == 0.0 and pulse_start_s == 0.0
    if p_start == 0.0:
        return force

    return 0.0

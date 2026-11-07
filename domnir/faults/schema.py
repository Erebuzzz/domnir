"""Admissible environmental disturbances and realistic fault models."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class WindGust3D(BaseModel):
    force_x_n: float = Field(default=0.0, ge=-0.20, le=0.20)
    force_y_n: float = Field(default=0.0, ge=-0.20, le=0.20)
    force_z_n: float = Field(default=0.0, ge=-0.20, le=0.20)
    start_s: float = Field(default=0.0, ge=0.0)
    duration_s: float = Field(default=0.0, ge=0.0, le=10.0)

    def is_active(self, t: float) -> bool:
        return self.start_s <= t <= (self.start_s + self.duration_s)

    def force_vector_at(self, t: float) -> list[float]:
        if self.is_active(t):
            return [self.force_x_n, self.force_y_n, self.force_z_n]
        return [0.0, 0.0, 0.0]


class SensorFaultSchedule(BaseModel):
    noise_pos_std_m: float = Field(default=0.0, ge=0.0, le=0.20)
    noise_vel_std_mps: float = Field(default=0.0, ge=0.0, le=0.50)
    bias_pos_m: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    latency_steps: int = Field(default=0, ge=0, le=20)
    dropout_probability: float = Field(default=0.0, ge=0.0, le=0.80)
    start_s: float = Field(default=0.0, ge=0.0)
    duration_s: float = Field(default=0.0, ge=0.0, le=10.0)

    def is_active(self, t: float) -> bool:
        return self.start_s <= t <= (self.start_s + self.duration_s)


class ActuatorFaultSchedule(BaseModel):
    thrust_multiplier: float = Field(default=1.0, ge=0.20, le=1.0)
    moment_multiplier: float = Field(default=1.0, ge=0.20, le=1.0)
    start_s: float = Field(default=0.0, ge=0.0)
    duration_s: float = Field(default=0.0, ge=0.0, le=10.0)

    def is_active(self, t: float) -> bool:
        return self.start_s <= t <= (self.start_s + self.duration_s)


class MissionFaultSchedule(BaseModel):
    wind_gusts: list[WindGust3D] = Field(default_factory=list)
    sensor_faults: list[SensorFaultSchedule] = Field(default_factory=list)
    actuator_faults: list[ActuatorFaultSchedule] = Field(default_factory=list)

"""Data models and configurations for plant uncertainty and sensitivity analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from pydantic import BaseModel, Field


class PlantUncertaintyConfig(BaseModel):
    """Configuration for physical plant model uncertainty and sensor degradation."""

    mass_scale: float = Field(default=1.0, ge=0.85, le=1.20)
    thrust_scale: float = Field(default=1.0, ge=0.80, le=1.25)
    drag_scale: float = Field(default=1.0, ge=0.70, le=1.50)
    position_noise_std_m: float = Field(default=0.0, ge=0.0, le=0.05)
    velocity_noise_std_mps: float = Field(default=0.0, ge=0.0, le=0.10)
    actuator_delay_steps: int = Field(default=0, ge=0, le=5)
    seed: int = Field(default=42, ge=0)


class ParameterizedSuite:
    """Standard suite of versioned test configurations for plant uncertainty."""

    SUITE_VERSION: str = "1.0.0"

    @classmethod
    def nominal(cls) -> PlantUncertaintyConfig:
        return PlantUncertaintyConfig()

    @classmethod
    def heavy_payload(cls) -> PlantUncertaintyConfig:
        return PlantUncertaintyConfig(mass_scale=1.12, thrust_scale=0.96)

    @classmethod
    def battery_depleted(cls) -> PlantUncertaintyConfig:
        return PlantUncertaintyConfig(thrust_scale=0.88)

    @classmethod
    def turbulent_drag(cls) -> PlantUncertaintyConfig:
        return PlantUncertaintyConfig(drag_scale=1.35)

    @classmethod
    def noisy_sensors(cls) -> PlantUncertaintyConfig:
        return PlantUncertaintyConfig(
            position_noise_std_m=0.008,
            velocity_noise_std_mps=0.02,
        )

    @classmethod
    def actuator_latency(cls) -> PlantUncertaintyConfig:
        return PlantUncertaintyConfig(actuator_delay_steps=2)

    @classmethod
    def get_suite(cls) -> dict[str, PlantUncertaintyConfig]:
        return {
            "nominal": cls.nominal(),
            "heavy_payload": cls.heavy_payload(),
            "battery_depleted": cls.battery_depleted(),
            "turbulent_drag": cls.turbulent_drag(),
            "noisy_sensors": cls.noisy_sensors(),
            "actuator_latency": cls.actuator_latency(),
        }

    @classmethod
    def all_variants(cls) -> dict[str, PlantUncertaintyConfig]:
        return cls.get_suite()


@dataclass
class SensitivityMetric:
    """Robustness sensitivity metric for a specific plant perturbation parameter."""

    parameter_name: str
    nominal_robustness: float
    perturbed_robustness: float
    sensitivity_coefficient: float
    causes_violation: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_name": self.parameter_name,
            "nominal_robustness": self.nominal_robustness,
            "perturbed_robustness": self.perturbed_robustness,
            "sensitivity_coefficient": self.sensitivity_coefficient,
            "causes_violation": self.causes_violation,
        }


@dataclass
class UncertaintyReport:
    """Adjudicated report across model uncertainty test variants."""

    total_variants_evaluated: int
    variants_passing: int
    variants_failing: int
    min_robustness_across_variants: float
    worst_variant_name: str
    most_sensitive_parameter: str
    parameter_sensitivities: list[SensitivityMetric]
    summary: str
    variant_robustness: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_variants_evaluated": self.total_variants_evaluated,
            "variants_passing": self.variants_passing,
            "variants_failing": self.variants_failing,
            "min_robustness_across_variants": self.min_robustness_across_variants,
            "worst_variant_name": self.worst_variant_name,
            "most_sensitive_parameter": self.most_sensitive_parameter,
            "parameter_sensitivities": [m.to_dict() for m in self.parameter_sensitivities],
            "summary": self.summary,
            "variant_robustness": self.variant_robustness,
        }

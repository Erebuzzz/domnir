"""Mission specification and stage models for 3D flight experiments."""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, model_validator


class MissionStageKind(str, Enum):
    TAKEOFF = "takeoff"
    WAYPOINT = "waypoint"
    CORRIDOR = "corridor"
    LANDING = "landing"
    RECOVERY = "recovery"


class MissionStage(BaseModel):
    id: str
    kind: MissionStageKind
    target_position_m: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.20])
    tolerance_m: float = Field(default=0.10, gt=0.0, le=2.0)
    dwell_s: float = Field(default=0.05, ge=0.0, le=5.0)
    completion_deadline_s: float = Field(default=5.0, gt=0.0, le=60.0)
    target_yaw_rad: float = Field(default=0.0, ge=-3.15, le=3.15)
    pad_id: str | None = None

    @model_validator(mode="after")
    def validate_stage(self) -> MissionStage:
        if len(self.target_position_m) != 3:
            raise ValueError(f"target_position_m must have exactly 3 coordinates [x, y, z], got {len(self.target_position_m)}")
        if self.kind == MissionStageKind.LANDING and not self.pad_id:
            self.pad_id = "default-landing-pad"
        return self


class MissionConstraints(BaseModel):
    min_altitude_m: float = Field(default=0.04, ge=0.0, le=2.0)
    max_altitude_m: float = Field(default=2.00, gt=0.1, le=10.0)
    max_speed_mps: float = Field(default=2.5, gt=0.1, le=10.0)
    max_tilt_deg: float = Field(default=45.0, gt=0.0, le=85.0)
    min_clearance_m: float = Field(default=0.05, ge=0.0, le=1.0)
    max_landing_impact_speed_mps: float = Field(default=0.40, gt=0.0, le=2.0)
    fail_on_unpermitted_contact: bool = True


class MissionSpecV2(BaseModel):
    schema_version: str = "mission-v2"
    mission_id: str
    world_id: str = "open-field"
    coordinate_frame: str = "world-z-up-right-handed"
    physics_dt_s: float = Field(default=0.002, frozen=True)
    controller_dt_s: float = Field(default=0.002, ge=0.002, le=0.02)
    stages: list[MissionStage] = Field(min_length=1)
    constraints: MissionConstraints = Field(default_factory=MissionConstraints)
    allowed_scenario_variations: dict[str, Any] = Field(default_factory=dict)
    random_seed: int = 42

    @property
    def total_mission_duration_s(self) -> float:
        return self.stages[-1].completion_deadline_s

    @property
    def physics_steps(self) -> int:
        return int(round(self.total_mission_duration_s / self.physics_dt_s))

    @classmethod
    def from_flight_spec(cls, spec: Any) -> MissionSpecV2:
        """Backwards compatibility adapter from legacy FlightSpec."""
        target_z = getattr(spec, "target_altitude_m", 0.10)
        duration = getattr(spec, "mission_duration_s", 0.40)
        dt = getattr(spec, "dt_s", 0.002)
        min_alt = getattr(spec, "min_allowed_altitude_m", 0.05)
        max_alt = getattr(spec, "max_allowed_altitude_m", 1.00)

        stages = [
            MissionStage(
                id="takeoff",
                kind=MissionStageKind.TAKEOFF,
                target_position_m=[0.0, 0.0, target_z],
                tolerance_m=getattr(spec, "altitude_tolerance_m", 0.05),
                dwell_s=min(0.05, duration * 0.2),
                completion_deadline_s=duration * 0.4,
            ),
            MissionStage(
                id="hover",
                kind=MissionStageKind.WAYPOINT,
                target_position_m=[0.0, 0.0, target_z],
                tolerance_m=getattr(spec, "altitude_tolerance_m", 0.05),
                dwell_s=min(0.10, duration * 0.4),
                completion_deadline_s=duration,
            ),
        ]
        return cls(
            mission_id=f"legacy-{int(target_z * 100)}cm",
            world_id="open-field",
            physics_dt_s=dt,
            controller_dt_s=dt,
            stages=stages,
            constraints=MissionConstraints(
                min_altitude_m=min_alt,
                max_altitude_m=max_alt,
            ),
        )

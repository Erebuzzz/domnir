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


class StageTimeoutPolicy(str, Enum):
    """What the tracker does when the active stage misses its deadline.

    ABORT: the stage is TIMED_OUT, every later stage is ABORTED, and the
    controller keeps receiving the timed-out stage's target until the
    scheduled end of the flight so physical safety is still evaluated over
    the whole window.
    ADVANCE: the stage is TIMED_OUT and the tracker moves on to the next
    stage, so later stages can still be attempted (and judged on their own
    deadlines). The mission verdict is NOT_COMPLETED either way.
    """

    ABORT = "abort"
    ADVANCE = "advance"


MAX_MISSION_STAGES = 12


class MissionSpecV2(BaseModel):
    schema_version: str = "mission-v2"
    mission_id: str
    world_id: str = "open-field"
    coordinate_frame: str = "world-z-up-right-handed"
    physics_dt_s: float = Field(default=0.002, frozen=True)
    controller_dt_s: float = Field(default=0.002, ge=0.002, le=0.02)
    stages: list[MissionStage] = Field(min_length=1, max_length=MAX_MISSION_STAGES)
    stage_timeout_policy: StageTimeoutPolicy = StageTimeoutPolicy.ABORT
    constraints: MissionConstraints = Field(default_factory=MissionConstraints)
    allowed_scenario_variations: dict[str, Any] = Field(default_factory=dict)
    random_seed: int = 42

    @model_validator(mode="after")
    def validate_controller_rate(self) -> MissionSpecV2:
        # The controller runs as a zero-order hold over whole physics steps.
        ratio = self.controller_dt_s / self.physics_dt_s
        if abs(ratio - round(ratio)) > 1e-9:
            raise ValueError(
                f"controller_dt_s {self.controller_dt_s} must be a whole multiple of "
                f"physics_dt_s {self.physics_dt_s}"
            )
        return self

    @property
    def controller_period_steps(self) -> int:
        return int(round(self.controller_dt_s / self.physics_dt_s))

    @model_validator(mode="after")
    def validate_stage_deadlines(self) -> MissionSpecV2:
        # Stages run in order, so their deadlines must not go backwards. The
        # last deadline is also the scheduled end of the flight.
        previous = 0.0
        for stage in self.stages:
            if stage.completion_deadline_s < previous:
                raise ValueError(
                    f"Stage '{stage.id}' deadline {stage.completion_deadline_s}s is earlier "
                    f"than the previous stage deadline {previous}s; deadlines must be non-decreasing"
                )
            previous = stage.completion_deadline_s
        return self

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

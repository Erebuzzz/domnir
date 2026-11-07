"""Signal Temporal Logic (STL) quantitative robustness engine for flight safety contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Self
from pydantic import BaseModel, Field, model_validator


class PredicateType(str, Enum):
    FLOOR = "floor"
    CEILING = "ceiling"
    TRACKING = "tracking"
    TILT = "tilt"
    VELOCITY = "velocity"


@dataclass(frozen=True)
class PredicateRobustness:
    predicate_type: PredicateType
    name: str
    robustness: float
    margin: float
    threshold: float
    actual_value: float


@dataclass(frozen=True)
class InstantaneousRobustness:
    timestamp_s: float
    step_index: int
    overall_robustness: float
    critical_predicate: PredicateType
    predicates: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class STLRobustnessResult:
    satisfied: bool
    verdict: str
    min_robustness: float
    critical_timestamp_s: float
    critical_step_index: int
    critical_predicate: str
    critical_actual_value: float
    critical_threshold: float
    summary: str
    timeline: list[InstantaneousRobustness] = field(default_factory=list)
    is_valid: bool = True


class SafetyContract(BaseModel):
    target_altitude_m: float = Field(default=0.10, gt=0.0, le=5.0)
    altitude_tolerance_m: float = Field(default=0.05, gt=0.0, le=1.0)
    min_allowed_altitude_m: float = Field(default=0.05, ge=0.0, le=2.0)
    max_allowed_altitude_m: float = Field(default=1.00, gt=0.05, le=10.0)
    max_tilt_deg: float = Field(default=45.0, gt=0.0, le=90.0)
    max_velocity_mps: float = Field(default=3.0, gt=0.1, le=20.0)
    settling_time_s: float = Field(default=0.15, ge=0.0, le=5.0)
    physics_dt_s: float = Field(default=0.002, frozen=True)
    controller_dt_s: float = Field(default=0.010, ge=0.002, le=0.100)
    mission_duration_s: float = Field(default=0.40, ge=0.02, le=10.0)

    @property
    def physics_steps(self) -> int:
        return int(round(self.mission_duration_s / self.physics_dt_s))

    @property
    def decimation(self) -> int:
        ratio = round(self.controller_dt_s / self.physics_dt_s)
        return max(1, int(ratio))

    @model_validator(mode="after")
    def validate_contract_bounds(self) -> Self:
        if self.min_allowed_altitude_m >= self.max_allowed_altitude_m:
            raise ValueError("Minimum altitude must be strictly less than maximum altitude")
        if self.target_altitude_m <= self.min_allowed_altitude_m:
            raise ValueError("Target altitude must be strictly above minimum safety floor")
        if self.target_altitude_m >= self.max_allowed_altitude_m:
            raise ValueError("Target altitude must be strictly below maximum safety ceiling")
        if self.settling_time_s >= self.mission_duration_s:
            raise ValueError("Settling time cannot exceed or equal mission duration")
        return self

    @classmethod
    def from_flight_spec(cls, spec: Any) -> SafetyContract:
        return cls(
            target_altitude_m=getattr(spec, "target_altitude_m", 0.10),
            altitude_tolerance_m=getattr(spec, "altitude_tolerance_m", 0.05),
            min_allowed_altitude_m=getattr(spec, "min_allowed_altitude_m", 0.05),
            max_allowed_altitude_m=getattr(spec, "max_allowed_altitude_m", 1.00),
            mission_duration_s=getattr(spec, "mission_duration_s", 0.40),
            physics_dt_s=getattr(spec, "dt_s", 0.002),
        )


class STLMonitor:
    @staticmethod
    def calculate_tilt_rad(orientation_quat_wxyz: list[float] | tuple[float, ...]) -> float:
        if len(orientation_quat_wxyz) < 4:
            return 0.0
        w, x, y, z = orientation_quat_wxyz[:4]
        # Body z-axis in world frame dot [0, 0, 1]
        cos_tilt = w * w - x * x - y * y + z * z
        cos_tilt_clipped = max(-1.0, min(1.0, float(cos_tilt)))
        return math.acos(cos_tilt_clipped)

    @classmethod
    def evaluate_trajectory(
        cls,
        contract: SafetyContract,
        trajectory: list[dict[str, Any]],
        *,
        require_full_horizon: bool = True,
    ) -> STLRobustnessResult:
        if not trajectory:
            return STLRobustnessResult(
                satisfied=False,
                verdict="INVALID",
                min_robustness=0.0,
                critical_timestamp_s=0.0,
                critical_step_index=0,
                critical_predicate="empty_trajectory",
                critical_actual_value=0.0,
                critical_threshold=0.0,
                summary="Trajectory is empty. No telemetry recorded.",
                timeline=[],
                is_valid=False,
            )

        max_tilt_rad = math.radians(contract.max_tilt_deg)
        timeline: list[InstantaneousRobustness] = []

        global_min_rho = float("inf")
        crit_t = 0.0
        crit_step = 0
        crit_pred = PredicateType.FLOOR
        crit_val = 0.0
        crit_thresh = 0.0
        prev_sim_time = -1.0

        for record in trajectory:
            step_idx = int(record.get("step_index", 0))
            sim_time = float(record.get("sim_time_s", step_idx * contract.physics_dt_s))

            if prev_sim_time >= 0.0 and sim_time < prev_sim_time:
                return STLRobustnessResult(
                    satisfied=False,
                    verdict="INVALID",
                    min_robustness=0.0,
                    critical_timestamp_s=sim_time,
                    critical_step_index=step_idx,
                    critical_predicate="non_monotonic_time",
                    critical_actual_value=sim_time,
                    critical_threshold=prev_sim_time,
                    summary=f"Non-monotonic timestamp detected at step {step_idx} ({sim_time:.4f}s < {prev_sim_time:.4f}s)",
                    timeline=timeline,
                    is_valid=False,
                )
            prev_sim_time = sim_time

            pos = record.get("position_m", [0.0, 0.0, 0.0])
            vel = record.get("velocity_mps", [0.0, 0.0, 0.0])
            quat = record.get("orientation_quat_wxyz", [1.0, 0.0, 0.0, 0.0])

            if len(quat) < 4:
                return STLRobustnessResult(
                    satisfied=False,
                    verdict="INVALID",
                    min_robustness=0.0,
                    critical_timestamp_s=sim_time,
                    critical_step_index=step_idx,
                    critical_predicate="malformed_quaternion",
                    critical_actual_value=float(len(quat)),
                    critical_threshold=4.0,
                    summary=f"Malformed quaternion length {len(quat)} at step {step_idx}",
                    timeline=timeline,
                    is_valid=False,
                )

            q_norm_sq = sum(float(c) ** 2 for c in quat[:4])
            if not math.isfinite(q_norm_sq) or abs(math.sqrt(q_norm_sq) - 1.0) > 0.05:
                q_norm = math.sqrt(q_norm_sq) if (math.isfinite(q_norm_sq) and q_norm_sq >= 0.0) else 0.0
                return STLRobustnessResult(
                    satisfied=False,
                    verdict="INVALID",
                    min_robustness=0.0,
                    critical_timestamp_s=sim_time,
                    critical_step_index=step_idx,
                    critical_predicate="unnormalized_quaternion",
                    critical_actual_value=q_norm,
                    critical_threshold=1.0,
                    summary=f"Quaternion normalization breached tolerance (|q|={q_norm:.4f}) at step {step_idx}",
                    timeline=timeline,
                    is_valid=False,
                )

            z = float(pos[2]) if len(pos) > 2 else 0.0
            speed = math.sqrt(sum(float(v) ** 2 for v in vel[:3]))
            tilt = cls.calculate_tilt_rad(quat)

            if not (math.isfinite(z) and math.isfinite(speed) and math.isfinite(tilt)):
                return STLRobustnessResult(
                    satisfied=False,
                    verdict="INVALID",
                    min_robustness=0.0,
                    critical_timestamp_s=sim_time,
                    critical_step_index=step_idx,
                    critical_predicate="non_finite_state",
                    critical_actual_value=z if math.isfinite(z) else 0.0,
                    critical_threshold=0.0,
                    summary=f"Non-finite state (NaN/Inf) detected at step {step_idx} (t={sim_time:.4f}s)",
                    timeline=timeline,
                    is_valid=False,
                )

            # Quantitative robustness predicates:
            # 1. Floor: z(t) >= z_min => rho = z - z_min
            rho_floor = z - contract.min_allowed_altitude_m
            # 2. Ceiling: z(t) <= z_max => rho = z_max - z
            rho_ceiling = contract.max_allowed_altitude_m - z
            # 3. Tilt: tilt(t) <= tilt_max => rho = tilt_max - tilt
            rho_tilt = max_tilt_rad - tilt
            # 4. Velocity: speed(t) <= speed_max => rho = speed_max - speed
            rho_vel = contract.max_velocity_mps - speed

            active_predicates: list[tuple[PredicateType, float, float, float]] = [
                (PredicateType.FLOOR, rho_floor, z, contract.min_allowed_altitude_m),
                (PredicateType.CEILING, rho_ceiling, z, contract.max_allowed_altitude_m),
                (PredicateType.TILT, rho_tilt, math.degrees(tilt), contract.max_tilt_deg),
                (PredicateType.VELOCITY, rho_vel, speed, contract.max_velocity_mps),
            ]

            # 5. Tracking corridor: only evaluated after settling time
            if sim_time >= contract.settling_time_s:
                tracking_error = abs(z - contract.target_altitude_m)
                rho_tracking = contract.altitude_tolerance_m - tracking_error
                active_predicates.append(
                    (PredicateType.TRACKING, rho_tracking, tracking_error, contract.altitude_tolerance_m)
                )

            # Instantaneous minimum robustness across all active predicates
            step_min_pred = min(active_predicates, key=lambda item: item[1])
            step_rho = step_min_pred[1]

            timeline.append(
                InstantaneousRobustness(
                    timestamp_s=sim_time,
                    step_index=step_idx,
                    overall_robustness=step_rho,
                    critical_predicate=step_min_pred[0],
                    predicates={p[0].value: p[1] for p in active_predicates},
                )
            )

            if step_rho < global_min_rho:
                global_min_rho = step_rho
                crit_t = sim_time
                crit_step = step_idx
                crit_pred = step_min_pred[0]
                crit_val = step_min_pred[2]
                crit_thresh = step_min_pred[3]

        satisfied = global_min_rho >= 0.0

        # Horizon check: if no breach occurred, check if trajectory covered expected duration
        final_sim_time = float(trajectory[-1].get("sim_time_s", 0.0))
        final_step_idx = int(trajectory[-1].get("step_index", len(trajectory) - 1))
        expected_min_horizon = contract.mission_duration_s - (contract.physics_dt_s * 1.5)
        if satisfied and require_full_horizon and final_sim_time < expected_min_horizon:
            return STLRobustnessResult(
                satisfied=False,
                verdict="INVALID",
                min_robustness=0.0,
                critical_timestamp_s=final_sim_time,
                critical_step_index=final_step_idx,
                critical_predicate="truncated_horizon",
                critical_actual_value=final_sim_time,
                critical_threshold=contract.mission_duration_s,
                summary=(
                    f"Trajectory truncated at t={final_sim_time:.4f}s before required mission "
                    f"duration {contract.mission_duration_s:.4f}s without meeting full horizon."
                ),
                timeline=timeline,
                is_valid=False,
            )

        verdict = "SATISFIED" if satisfied else "VIOLATED"

        if satisfied:
            summary = (
                f"Contract satisfied with robustness margin +{global_min_rho:.4f}. "
                f"Most constrained predicate was {crit_pred.value} at t={crit_t:.3f}s."
            )
        else:
            summary = (
                f"Contract violated: robustness is {global_min_rho:.4f} (< 0). "
                f"Critical breach: {crit_pred.value} at t={crit_t:.3f}s (step {crit_step}) "
                f"with value {crit_val:.4f} against threshold {crit_thresh:.4f}."
            )

        return STLRobustnessResult(
            satisfied=satisfied,
            verdict=verdict,
            min_robustness=global_min_rho,
            critical_timestamp_s=crit_t,
            critical_step_index=crit_step,
            critical_predicate=crit_pred.value,
            critical_actual_value=crit_val,
            critical_threshold=crit_thresh,
            summary=summary,
            timeline=timeline,
            is_valid=True,
        )

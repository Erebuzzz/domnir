"""Multi-predicate 3D Safety and Mission Monitor."""

from __future__ import annotations

import math
from typing import Any
from pydantic import BaseModel, Field
from domnir.missions.schema import MissionSpecV2, MissionStageKind
from domnir.worlds.schema import EntityKind, WorldSpec


class ContactEvent(BaseModel):
    step_index: int
    sim_time_s: float
    geom1: str
    geom2: str
    contact_class: str  # "obstacle", "allowed-touchdown", "floor"
    impact_velocity_mps: float
    position_m: list[float] = Field(default_factory=list)


class MissionSafetyEvaluation(BaseModel):
    satisfied: bool
    physical_verdict: str  # "NOT_FALSIFIED", "FALSIFIED", "INVALID"
    mission_verdict: str   # "COMPLETED", "NOT_COMPLETED", "ABORTED"
    min_robustness: float
    critical_predicate: str
    critical_timestamp_s: float
    critical_step_index: int
    contacts_detected: list[ContactEvent] = Field(default_factory=list)
    stage_results: list[dict[str, Any]] = Field(default_factory=list)
    summary: str


class MissionSafetyMonitor:
    @classmethod
    def evaluate(
        cls,
        mission: MissionSpecV2,
        world: WorldSpec,
        trajectory: list[dict[str, Any]],
        contacts: list[ContactEvent],
        stage_history: list[dict[str, Any]],
    ) -> MissionSafetyEvaluation:
        if not trajectory:
            return MissionSafetyEvaluation(
                satisfied=False,
                physical_verdict="INVALID",
                mission_verdict="NOT_COMPLETED",
                min_robustness=-1.0,
                critical_predicate="empty_trajectory",
                critical_timestamp_s=0.0,
                critical_step_index=0,
                summary="Trajectory is empty. No telemetry recorded.",
            )

        constraints = mission.constraints
        stage_kind_map = {st.id: st.kind for st in mission.stages}
        min_rob = float("inf")
        crit_pred = "safe"
        crit_time = 0.0
        crit_step = 0
        physical_falsified = False
        reasons = []

        # 1. Trajectory frame checks
        for pt in trajectory:
            t = float(pt.get("sim_time_s", 0.0))
            step = int(pt.get("step_index", 0))
            pos = pt.get("position_m", [0.0, 0.0, 0.0])
            vel = pt.get("velocity_mps", [0.0, 0.0, 0.0])
            quat = pt.get("orientation_quat_wxyz", [1.0, 0.0, 0.0, 0.0])

            z = pos[2]
            speed = math.sqrt(vel[0] ** 2 + vel[1] ** 2 + vel[2] ** 2)

            # Tilt angle
            w, qx, qy, qz = quat[:4]
            cos_tilt = max(-1.0, min(1.0, w * w - qx * qx - qy * qy + qz * qz))
            tilt_deg = math.degrees(math.acos(cos_tilt))

            # Altitude floor (relaxed to 0.0 during intentional landing descent)
            st_kind = stage_kind_map.get(pt.get("active_stage_id"), MissionStageKind.WAYPOINT)
            effective_min_alt = 0.0 if st_kind == MissionStageKind.LANDING else constraints.min_altitude_m
            rob_floor = z - effective_min_alt
            if rob_floor < min_rob:
                min_rob = rob_floor
                crit_pred = "altitude_floor"
                crit_time = t
                crit_step = step

            # Altitude ceiling
            rob_ceil = constraints.max_altitude_m - z
            if rob_ceil < min_rob:
                min_rob = rob_ceil
                crit_pred = "altitude_ceiling"
                crit_time = t
                crit_step = step

            # Speed limit
            rob_speed = constraints.max_speed_mps - speed
            if rob_speed < min_rob:
                min_rob = rob_speed
                crit_pred = "speed_limit"
                crit_time = t
                crit_step = step

            # Tilt limit
            rob_tilt = constraints.max_tilt_deg - tilt_deg
            if rob_tilt < min_rob:
                min_rob = rob_tilt
                crit_pred = "tilt_limit"
                crit_time = t
                crit_step = step

            # Obstacle clearance check
            for ent in world.entities:
                ep = ent.pose.position_m
                dims = ent.dimensions_m

                if ent.kind == EntityKind.CYLINDER_OBSTACLE:
                    radius = dims[0] / 2.0
                    half_h = (dims[1] if len(dims) > 1 else 1.0) / 2.0
                    d_xy = math.sqrt((pos[0] - ep[0]) ** 2 + (pos[1] - ep[1]) ** 2)
                    d_z = max(0.0, abs(pos[2] - ep[2]) - half_h)
                    clearance = math.sqrt(max(0.0, d_xy - radius) ** 2 + d_z ** 2) - 0.045
                elif ent.kind in (EntityKind.BOX_OBSTACLE, EntityKind.WALL):
                    hx = dims[0] / 2.0
                    hy = (dims[1] if len(dims) > 1 else dims[0]) / 2.0
                    hz = (dims[2] if len(dims) > 2 else dims[0]) / 2.0
                    dx = max(0.0, abs(pos[0] - ep[0]) - hx)
                    dy = max(0.0, abs(pos[1] - ep[1]) - hy)
                    dz = max(0.0, abs(pos[2] - ep[2]) - hz)
                    clearance = math.sqrt(dx * dx + dy * dy + dz * dz) - 0.045
                else:
                    continue

                rob_clear = clearance - constraints.min_clearance_m
                if rob_clear < min_rob:
                    min_rob = rob_clear
                    crit_pred = f"clearance_{ent.id}"
                    crit_time = t
                    crit_step = step

        if min_rob <= 0.0:
            physical_falsified = True
            reasons.append(f"Hard constraint breach ({crit_pred}) with margin {min_rob:.4f} at t={crit_time:.3f}s")

        # 2. Collision contacts analysis
        forbidden_contacts = [c for c in contacts if c.contact_class == "obstacle"]
        if forbidden_contacts and constraints.fail_on_unpermitted_contact:
            physical_falsified = True
            first_c = forbidden_contacts[0]
            if not reasons:
                crit_pred = f"collision_{first_c.geom2}"
                crit_time = first_c.sim_time_s
                crit_step = first_c.step_index
                min_rob = -0.05
            reasons.append(f"Forbidden obstacle contact detected with '{first_c.geom2}' at t={first_c.sim_time_s:.3f}s")

        # 3. Landing impact analysis
        landing_contacts = [c for c in contacts if c.contact_class == "allowed-touchdown"]
        for lc in landing_contacts:
            if lc.impact_velocity_mps > constraints.max_landing_impact_speed_mps:
                physical_falsified = True
                reasons.append(
                    f"Landing impact speed {lc.impact_velocity_mps:.3f} m/s exceeded max allowed {constraints.max_landing_impact_speed_mps:.3f} m/s"
                )

        # 4. Mission completion check
        all_completed = len(stage_history) >= len(mission.stages) and all(
            st.get("status") == "COMPLETED" for st in stage_history
        )

        physical_verdict = "FALSIFIED" if physical_falsified else "NOT_FALSIFIED"
        mission_verdict = "COMPLETED" if all_completed else "NOT_COMPLETED"

        summary = (
            f"Physical verdict: {physical_verdict}. Mission state: {mission_verdict}. "
            f"Min robustness: {min_rob:.4f} ({crit_pred}). "
        )
        if reasons:
            summary += "; ".join(reasons)
        else:
            summary += "All physical flight boundaries and clearance limits respected."

        return MissionSafetyEvaluation(
            satisfied=not physical_falsified,
            physical_verdict=physical_verdict,
            mission_verdict=mission_verdict,
            min_robustness=round(float(min_rob), 5),
            critical_predicate=crit_pred,
            critical_timestamp_s=round(float(crit_time), 4),
            critical_step_index=crit_step,
            contacts_detected=contacts,
            stage_results=stage_history,
            summary=summary,
        )

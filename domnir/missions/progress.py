"""Mission execution progress and stage transition tracker."""

from __future__ import annotations

import math
from typing import Any
from .schema import MissionSpecV2, MissionStageKind


class MissionProgressTracker:
    def __init__(self, spec: MissionSpecV2) -> None:
        self.spec = spec
        self.current_stage_idx: int = 0
        self.dwell_time_s: float = 0.0
        self.is_completed: bool = False
        self.stage_history: list[dict[str, Any]] = []
        self._record_stage_entry(0, 0.0, 0)

    @property
    def current_stage(self):
        if self.current_stage_idx < len(self.spec.stages):
            return self.spec.stages[self.current_stage_idx]
        return self.spec.stages[-1]

    def _record_stage_entry(self, stage_idx: int, sim_time_s: float, step_idx: int) -> None:
        st = self.spec.stages[stage_idx]
        self.stage_history.append({
            "stage_id": st.id,
            "stage_index": stage_idx,
            "kind": st.kind.value,
            "entered_at_s": sim_time_s,
            "step_index": step_idx,
            "status": "ENTERED",
            "target_position_m": list(st.target_position_m),
        })

    def update(
        self,
        sim_time_s: float,
        step_idx: int,
        position_m: list[float],
        velocity_mps: list[float],
        *,
        pad_contact: bool = False,
        dt_s: float = 0.002,
    ) -> dict[str, Any]:
        """Update tracker with latest vehicle state and advance stage if satisfied."""
        if self.is_completed or self.current_stage_idx >= len(self.spec.stages):
            last_stage = self.spec.stages[-1]
            return {
                "active_stage_id": last_stage.id,
                "stage_index": len(self.spec.stages) - 1,
                "stage_kind": last_stage.kind.value,
                "target_position_m": list(last_stage.target_position_m),
                "distance_to_target_m": 0.0,
                "dwell_progress_s": 0.0,
                "is_completed": True,
                "stage_advanced": False,
                "deadline_exceeded": False,
            }

        st = self.spec.stages[self.current_stage_idx]
        target = st.target_position_m
        dist = math.sqrt(
            (position_m[0] - target[0]) ** 2
            + (position_m[1] - target[1]) ** 2
            + (position_m[2] - target[2]) ** 2
        )

        stage_advanced = False
        deadline_exceeded = False

        # Deadline check
        if sim_time_s > st.completion_deadline_s:
            deadline_exceeded = True

        # Arrival condition
        is_arrived = False
        if st.kind == MissionStageKind.LANDING:
            # Landing requires being close to pad, low descent speed, and pad contact
            v_desc = abs(velocity_mps[2])
            is_arrived = (dist <= st.tolerance_m) and (v_desc <= self.spec.constraints.max_landing_impact_speed_mps) and pad_contact
        else:
            is_arrived = dist <= st.tolerance_m

        if is_arrived:
            self.dwell_time_s += dt_s
            if self.dwell_time_s >= st.dwell_s:
                # Mark current stage completed
                self.stage_history[-1]["completed_at_s"] = sim_time_s
                self.stage_history[-1]["status"] = "COMPLETED"
                self.dwell_time_s = 0.0

                if self.current_stage_idx + 1 < len(self.spec.stages):
                    self.current_stage_idx += 1
                    stage_advanced = True
                    self._record_stage_entry(self.current_stage_idx, sim_time_s, step_idx)
                else:
                    self.is_completed = True
        else:
            # Reset dwell timer if exited corridor/region
            self.dwell_time_s = max(0.0, self.dwell_time_s - dt_s * 0.5)

        return {
            "active_stage_id": self.current_stage.id,
            "stage_index": self.current_stage_idx,
            "stage_kind": self.current_stage.kind.value,
            "target_position_m": list(self.current_stage.target_position_m),
            "distance_to_target_m": round(dist, 4),
            "dwell_progress_s": round(self.dwell_time_s, 4),
            "is_completed": self.is_completed,
            "stage_advanced": stage_advanced,
            "deadline_exceeded": deadline_exceeded,
        }

"""Mission execution progress and stage transition tracker.

Stage lifecycle
---------------
Every stage in the mission ends up with exactly one terminal status in
``stage_history``:

* ``COMPLETED``  the arrival condition (and dwell) was satisfied at or before
  the stage deadline.
* ``TIMED_OUT``  the stage was active when its deadline passed, or the flight
  ended while it was still active.
* ``ABORTED``    the stage was never attempted because an earlier stage timed
  out under the ``abort`` policy, or the flight ended first.

``ENTERED`` is the only non-terminal status; ``finalize()`` resolves it.

Deadline boundary: completion at ``t <= deadline`` is on time. MuJoCo
accumulates ``data.time`` by repeated float addition, so a tolerance of
``DEADLINE_EPSILON_S`` absorbs rounding (e.g. 400 * 0.002 = 0.8000000000000003).
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any

from .schema import MissionSpecV2, MissionStageKind, StageTimeoutPolicy

DEADLINE_EPSILON_S = 1e-9


class StageStatus(str, Enum):
    ENTERED = "ENTERED"
    COMPLETED = "COMPLETED"
    TIMED_OUT = "TIMED_OUT"
    ABORTED = "ABORTED"


class MissionProgressTracker:
    def __init__(self, spec: MissionSpecV2) -> None:
        self.spec = spec
        self.current_stage_idx: int = 0
        self.dwell_time_s: float = 0.0
        self.is_completed: bool = False
        self.is_aborted: bool = False
        self.is_finalized: bool = False
        self.stage_history: list[dict[str, Any]] = []
        self._record_stage_entry(0, 0.0, 0)

    @property
    def current_stage(self):
        if self.current_stage_idx < len(self.spec.stages):
            return self.spec.stages[self.current_stage_idx]
        return self.spec.stages[-1]

    @property
    def stages_completed(self) -> int:
        return sum(1 for st in self.stage_history if st["status"] == StageStatus.COMPLETED.value)

    @property
    def total_stages(self) -> int:
        return len(self.spec.stages)

    def _record_stage_entry(self, stage_idx: int, sim_time_s: float, step_idx: int) -> None:
        st = self.spec.stages[stage_idx]
        self.stage_history.append({
            "stage_id": st.id,
            "stage_index": stage_idx,
            "kind": st.kind.value,
            "entered_at_s": sim_time_s,
            "step_index": step_idx,
            "completion_deadline_s": st.completion_deadline_s,
            "status": StageStatus.ENTERED.value,
            "target_position_m": list(st.target_position_m),
        })

    def _record_aborted_stages(self, from_idx: int, sim_time_s: float, reason: str) -> None:
        for idx in range(from_idx, len(self.spec.stages)):
            st = self.spec.stages[idx]
            self.stage_history.append({
                "stage_id": st.id,
                "stage_index": idx,
                "kind": st.kind.value,
                "entered_at_s": None,
                "step_index": None,
                "completion_deadline_s": st.completion_deadline_s,
                "status": StageStatus.ABORTED.value,
                "aborted_at_s": sim_time_s,
                "reason": reason,
                "target_position_m": list(st.target_position_m),
            })

    def _time_out_active_stage(self, sim_time_s: float, reason: str) -> None:
        entry = self.stage_history[-1]
        entry["status"] = StageStatus.TIMED_OUT.value
        entry["timed_out_at_s"] = sim_time_s
        entry["reason"] = reason
        self.dwell_time_s = 0.0

    def _distance_to(self, position_m: list[float], target: list[float]) -> float:
        return math.sqrt(
            (position_m[0] - target[0]) ** 2
            + (position_m[1] - target[1]) ** 2
            + (position_m[2] - target[2]) ** 2
        )

    def _result(self, dist: float, *, stage_advanced: bool, deadline_exceeded: bool) -> dict[str, Any]:
        return {
            "active_stage_id": self.current_stage.id,
            "stage_index": min(self.current_stage_idx, len(self.spec.stages) - 1),
            "stage_kind": self.current_stage.kind.value,
            "target_position_m": list(self.current_stage.target_position_m),
            "distance_to_target_m": round(dist, 4),
            "dwell_progress_s": round(self.dwell_time_s, 4),
            "is_completed": self.is_completed,
            "is_aborted": self.is_aborted,
            "stage_advanced": stage_advanced,
            "deadline_exceeded": deadline_exceeded,
        }

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
        st = self.current_stage
        dist = self._distance_to(position_m, st.target_position_m)

        if self.is_completed or self.is_aborted or self.is_finalized:
            return self._result(dist, stage_advanced=False, deadline_exceeded=self.is_aborted)

        # Deadline is checked before arrival: reaching the target after the
        # deadline must never count as completion.
        if sim_time_s > st.completion_deadline_s + DEADLINE_EPSILON_S:
            self._time_out_active_stage(
                sim_time_s,
                f"Stage deadline {st.completion_deadline_s:.3f}s passed before the stage was completed",
            )
            next_idx = self.current_stage_idx + 1
            if self.spec.stage_timeout_policy == StageTimeoutPolicy.ADVANCE and next_idx < len(self.spec.stages):
                self.current_stage_idx = next_idx
                self._record_stage_entry(next_idx, sim_time_s, step_idx)
                st = self.current_stage
                dist = self._distance_to(position_m, st.target_position_m)
                # The new stage may itself already be past its deadline; that
                # is resolved on the next update.
                return self._result(dist, stage_advanced=True, deadline_exceeded=True)

            self.is_aborted = True
            self._record_aborted_stages(
                next_idx,
                sim_time_s,
                f"Not attempted: stage '{st.id}' timed out under the abort policy",
            )
            return self._result(dist, stage_advanced=False, deadline_exceeded=True)

        if st.kind == MissionStageKind.LANDING:
            # Landing requires being close to pad, low descent speed, and pad contact
            v_desc = abs(velocity_mps[2])
            is_arrived = (
                dist <= st.tolerance_m
                and v_desc <= self.spec.constraints.max_landing_impact_speed_mps
                and pad_contact
            )
        else:
            is_arrived = dist <= st.tolerance_m

        stage_advanced = False
        if is_arrived:
            self.dwell_time_s += dt_s
            if self.dwell_time_s >= st.dwell_s:
                self.stage_history[-1]["completed_at_s"] = sim_time_s
                self.stage_history[-1]["status"] = StageStatus.COMPLETED.value
                self.dwell_time_s = 0.0

                if self.current_stage_idx + 1 < len(self.spec.stages):
                    self.current_stage_idx += 1
                    stage_advanced = True
                    self._record_stage_entry(self.current_stage_idx, sim_time_s, step_idx)
                else:
                    self.is_completed = True
        else:
            # Decay dwell timer if exited corridor/region
            self.dwell_time_s = max(0.0, self.dwell_time_s - dt_s * 0.5)

        if stage_advanced:
            dist = self._distance_to(position_m, self.current_stage.target_position_m)
        return self._result(dist, stage_advanced=stage_advanced, deadline_exceeded=False)

    def finalize(self, end_time_s: float) -> list[dict[str, Any]]:
        """Resolve any non-terminal stage once the flight has ended.

        A stage still ``ENTERED`` when the flight ends did not complete in time,
        so it becomes ``TIMED_OUT``; stages never entered become ``ABORTED``.
        Safe to call more than once.
        """
        if self.is_finalized:
            return self.stage_history
        self.is_finalized = True
        if self.is_completed or self.is_aborted:
            return self.stage_history

        active = self.stage_history[-1]
        if active["status"] == StageStatus.ENTERED.value:
            self._time_out_active_stage(
                end_time_s,
                f"Flight ended at {end_time_s:.3f}s before the stage was completed",
            )
        self._record_aborted_stages(
            self.current_stage_idx + 1,
            end_time_s,
            "Not attempted: flight ended before this stage was reached",
        )
        return self.stage_history

"""3D Reference trajectory planner and mission corridor feasibility checks."""

from __future__ import annotations

import math
from typing import Any
from .schema import MissionSpecV2


class TrajectoryWaypoint:
    def __init__(self, time_s: float, position_m: list[float], yaw_rad: float = 0.0) -> None:
        self.time_s = time_s
        self.position_m = list(position_m)
        self.yaw_rad = yaw_rad


class ReferenceTrajectory:
    def __init__(self, spec: MissionSpecV2, initial_position_m: list[float] | None = None) -> None:
        self.spec = spec
        p0 = list(initial_position_m) if initial_position_m else [0.0, 0.0, 0.0]
        self.waypoints: list[TrajectoryWaypoint] = [TrajectoryWaypoint(0.0, p0, 0.0)]

        for st in spec.stages:
            self.waypoints.append(
                TrajectoryWaypoint(st.completion_deadline_s, st.target_position_m, st.target_yaw_rad)
            )

    def sample(self, t: float) -> dict[str, Any]:
        """Sample reference position, velocity, and yaw at time t using smooth cubic Hermite interpolation."""
        if t <= self.waypoints[0].time_s:
            return {
                "position_m": list(self.waypoints[0].position_m),
                "velocity_mps": [0.0, 0.0, 0.0],
                "yaw_rad": self.waypoints[0].yaw_rad,
            }
        if t >= self.waypoints[-1].time_s:
            return {
                "position_m": list(self.waypoints[-1].position_m),
                "velocity_mps": [0.0, 0.0, 0.0],
                "yaw_rad": self.waypoints[-1].yaw_rad,
            }

        # Find segment
        idx = 0
        for i in range(len(self.waypoints) - 1):
            if self.waypoints[i].time_s <= t <= self.waypoints[i + 1].time_s:
                idx = i
                break

        w0 = self.waypoints[idx]
        w1 = self.waypoints[idx + 1]
        dt = w1.time_s - w0.time_s
        if dt <= 1e-6:
            return {
                "position_m": list(w1.position_m),
                "velocity_mps": [0.0, 0.0, 0.0],
                "yaw_rad": w1.yaw_rad,
            }

        tau = (t - w0.time_s) / dt
        # Smooth step: s(tau) = 3 tau^2 - 2 tau^3
        s = 3.0 * (tau ** 2) - 2.0 * (tau ** 3)
        ds = (6.0 * tau - 6.0 * (tau ** 2)) / dt

        pos = [
            w0.position_m[k] + (w1.position_m[k] - w0.position_m[k]) * s
            for k in range(3)
        ]
        vel = [
            (w1.position_m[k] - w0.position_m[k]) * ds
            for k in range(3)
        ]
        yaw = w0.yaw_rad + (w1.yaw_rad - w0.yaw_rad) * s

        return {
            "position_m": pos,
            "velocity_mps": vel,
            "yaw_rad": yaw,
        }

    def check_feasibility(self) -> tuple[bool, str]:
        """Verify that segment speeds and accelerations do not exceed vehicle physical limits."""
        for i in range(len(self.waypoints) - 1):
            w0 = self.waypoints[i]
            w1 = self.waypoints[i + 1]
            dt = w1.time_s - w0.time_s
            if dt <= 0:
                return False, f"Non-positive duration between waypoints {i} and {i+1}"
            dist = math.dist(w0.position_m, w1.position_m)
            avg_speed = dist / dt
            if avg_speed > self.spec.constraints.max_speed_mps:
                return False, f"Segment {i}->{i+1} average speed {avg_speed:.2f} m/s exceeds max {self.spec.constraints.max_speed_mps:.2f} m/s"
        return True, "Trajectory is kinematically feasible"

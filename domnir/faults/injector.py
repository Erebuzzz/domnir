"""Fault and environmental disturbance injection runtime."""

from __future__ import annotations

import collections
import random
from typing import Any
from .schema import MissionFaultSchedule


class FaultInjector:
    def __init__(self, schedule: MissionFaultSchedule | None = None, *, seed: int = 42) -> None:
        self.schedule = schedule or MissionFaultSchedule()
        self.rng = random.Random(seed)
        self.obs_buffer: collections.deque[dict[str, Any]] = collections.deque()

    def get_applied_wind_force_n(self, t: float) -> list[float]:
        total_fx = 0.0
        total_fy = 0.0
        total_fz = 0.0
        for gust in self.schedule.wind_gusts:
            if gust.is_active(t):
                f = gust.force_vector_at(t)
                total_fx += f[0]
                total_fy += f[1]
                total_fz += f[2]
        return [round(total_fx, 6), round(total_fy, 6), round(total_fz, 6)]

    def apply_sensor_faults(self, true_obs: dict[str, Any], t: float) -> dict[str, Any]:
        """Produce faulted observation for guest controller while keeping truth untouched."""
        # Deep copy relevant fields
        faulted = dict(true_obs)
        faulted["position_m"] = list(true_obs.get("position_m", [0.0, 0.0, 0.0]))
        faulted["velocity_mps"] = list(true_obs.get("velocity_mps", [0.0, 0.0, 0.0]))

        active_fault = None
        for sf in self.schedule.sensor_faults:
            if sf.is_active(t):
                active_fault = sf
                break

        if active_fault is not None:
            # 1. Packet dropout
            if active_fault.dropout_probability > 0.0:
                if self.rng.random() < active_fault.dropout_probability:
                    # Stale reading: keep previous buffered observation if available
                    if self.obs_buffer:
                        return dict(self.obs_buffer[-1])

            # 2. Additive Gaussian noise
            if active_fault.noise_pos_std_m > 0.0:
                for k in range(3):
                    faulted["position_m"][k] += self.rng.gauss(0.0, active_fault.noise_pos_std_m)

            if active_fault.noise_vel_std_mps > 0.0:
                for k in range(3):
                    faulted["velocity_mps"][k] += self.rng.gauss(0.0, active_fault.noise_vel_std_mps)

            # 3. Constant sensor bias
            if active_fault.bias_pos_m:
                for k in range(min(3, len(active_fault.bias_pos_m))):
                    faulted["position_m"][k] += active_fault.bias_pos_m[k]

            # 4. Latency queue
            if active_fault.latency_steps > 0:
                self.obs_buffer.append(dict(faulted))
                if len(self.obs_buffer) > active_fault.latency_steps:
                    return self.obs_buffer.popleft()
                return dict(self.obs_buffer[0])

        return faulted

    def apply_actuator_derating(
        self,
        action: tuple[float, float, float, float],
        t: float,
    ) -> tuple[float, float, float, float]:
        thrust, mx, my, mz = action
        for af in self.schedule.actuator_faults:
            if af.is_active(t):
                thrust *= af.thrust_multiplier
                mx *= af.moment_multiplier
                my *= af.moment_multiplier
                mz *= af.moment_multiplier
        return (thrust, mx, my, mz)

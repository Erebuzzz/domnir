"""Deterministic 6-DoF cascaded SE(3) tracking controller for Bitcraze Crazyflie 2.0."""

from __future__ import annotations

import math
from typing import Any


class Baseline3DController:
    """Nonlinear SE(3) geometric tracking controller emitting Protocol 1.0 frames."""

    def __init__(
        self,
        *,
        mass_kg: float = 0.027,
        gravity_mps2: float = 9.81,
        # Gains are derived from the pinned cf2.xml model: each moment command
        # in [-1, 1] produces 1e-5 N*m (actuator gear), and the body inertia
        # is Ixx = Iyy = 2.3951e-5, Izz = 3.2347e-5 kg*m^2. The full-scale
        # angular acceleration is therefore only ~0.42 rad/s^2 (roll/pitch),
        # so the attitude loop is tuned to wn = 4 rad/s, zeta = 0.9
        # (kp = wn^2 * I / 1e-5, kd = 2 * zeta * wn * I / 1e-5) and yaw to
        # wn = 1.5 rad/s. The horizontal position loop (wn = 1.2 rad/s) and
        # tilt limit (0.30 rad) keep the outer loop slower than attitude.
        kp_pos: tuple[float, float, float] = (1.44, 1.44, 6.5),
        kd_pos: tuple[float, float, float] = (2.16, 2.16, 3.2),
        kp_att: tuple[float, float, float] = (38.32, 38.32, 7.278),
        kd_att: tuple[float, float, float] = (17.245, 17.245, 8.734),
        max_thrust_n: float = 0.35,
        min_thrust_n: float = 0.0,
        max_tilt_rad: float = 0.30,
    ) -> None:
        self.mass = mass_kg
        self.g = gravity_mps2
        self.kp_pos = kp_pos
        self.kd_pos = kd_pos
        self.kp_att = kp_att
        self.kd_att = kd_att
        self.max_thrust = max_thrust_n
        self.min_thrust = min_thrust_n
        self.max_tilt = max_tilt_rad

    def compute_action(
        self,
        observation: dict[str, Any],
        target_pos_m: list[float] | None = None,
        target_vel_mps: list[float] | None = None,
        target_yaw_rad: float = 0.0,
    ) -> dict[str, Any]:
        trial_id = str(observation.get("trial_id", "trial-default"))
        step_index = int(observation.get("step_index", 0))

        pos = observation.get("position_m", [0.0, 0.0, 0.0])
        vel = observation.get("velocity_mps", [0.0, 0.0, 0.0])
        quat = observation.get("orientation_quat_wxyz", [1.0, 0.0, 0.0, 0.0])
        omega = observation.get("body_angular_velocity_rps", [0.0, 0.0, 0.0])

        if target_pos_m is None:
            target_pos_m = observation.get("target_position_m", [0.0, 0.0, 0.20])
        if target_vel_mps is None:
            target_vel_mps = [0.0, 0.0, 0.0]

        # 1. Position error
        ex = pos[0] - target_pos_m[0]
        ey = pos[1] - target_pos_m[1]
        ez = pos[2] - target_pos_m[2]

        evx = vel[0] - target_vel_mps[0]
        evy = vel[1] - target_vel_mps[1]
        evz = vel[2] - target_vel_mps[2]

        # 2. Desired acceleration
        ax = -self.kp_pos[0] * ex - self.kd_pos[0] * evx
        ay = -self.kp_pos[1] * ey - self.kd_pos[1] * evy
        az = -self.kp_pos[2] * ez - self.kd_pos[2] * evz + self.g

        # Tilt limit to prevent inverted flips
        a_horiz = math.sqrt(ax * ax + ay * ay)
        max_horiz_acc = self.g * math.tan(self.max_tilt)
        if a_horiz > max_horiz_acc and a_horiz > 1e-6:
            scale = max_horiz_acc / a_horiz
            ax *= scale
            ay *= scale

        # 3. Orientation to rotation matrix R (MuJoCo quat WXYZ)
        w, qx, qy, qz = quat[:4]
        # Body z-axis in world coordinates
        zb_x = 2.0 * (qx * qz + w * qy)
        zb_y = 2.0 * (qy * qz - w * qx)
        zb_z = w * w - qx * qx - qy * qy + qz * qz

        # Collective thrust along body Z
        thrust_proj = ax * zb_x + ay * zb_y + az * zb_z
        total_thrust = self.mass * thrust_proj
        total_thrust = max(self.min_thrust, min(self.max_thrust, total_thrust))

        # 4. Desired body attitude angles (small-angle approximation for roll and pitch)
        # Pitch theta aligns with ax: forward pitch pitches body nose down (+ax requires +pitch)
        pitch_des = math.atan2(ax, az)
        # Roll phi aligns with -ay: right roll tilts thrust right (+ay requires -roll)
        roll_des = math.atan2(-ay, az)

        # Current pitch and roll from quaternion
        # sin(pitch) = 2(w*qy - qx*qz)
        sin_pitch = max(-1.0, min(1.0, 2.0 * (w * qy - qx * qz)))
        current_pitch = math.asin(sin_pitch)
        # roll = atan2(2(w*qx + qy*qz), 1 - 2(qx^2 + qy^2))
        current_roll = math.atan2(2.0 * (w * qx + qy * qz), 1.0 - 2.0 * (qx * qx + qy * qy))
        # yaw = atan2(2(w*qz + qx*qy), 1 - 2(qy^2 + qz^2))
        current_yaw = math.atan2(2.0 * (w * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))

        # Attitude error
        err_roll = roll_des - current_roll
        err_pitch = pitch_des - current_pitch
        err_yaw = (target_yaw_rad - current_yaw + math.pi) % (2.0 * math.pi) - math.pi

        # 5. Moments with rate damping
        # cf2.xml actuator gear is negative (-1e-5) on all three moment axes,
        # reversing moment direction relative to the body frame. Yaw needs the
        # same sign flip as roll and pitch; without it the yaw loop is
        # positive feedback and diverges once pad contact disturbs yaw.
        mx = -(self.kp_att[0] * err_roll - self.kd_att[0] * omega[0])
        my = -(self.kp_att[1] * err_pitch - self.kd_att[1] * omega[1])
        mz = -(self.kp_att[2] * err_yaw - self.kd_att[2] * omega[2])

        # Clamp moments to [-1.0, 1.0]
        mx = max(-1.0, min(1.0, mx))
        my = max(-1.0, min(1.0, my))
        mz = max(-1.0, min(1.0, mz))

        return {
            "schema_version": "1.0",
            "trial_id": trial_id,
            "step_index": step_index,
            "thrust": round(float(total_thrust), 5),
            "moment_x": round(float(mx), 5),
            "moment_y": round(float(my), 5),
            "moment_z": round(float(mz), 5),
        }

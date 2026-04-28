"""Motion prediction tracker used by the aim loop."""

from __future__ import annotations

import math
from typing import Tuple

# Reasonable cap on per-frame estimated acceleration (screen px / s^2). Anything
# beyond this is almost certainly detector noise rather than a real player.
_ACCEL_CAP_PX_PER_S2 = 20000.0
_ACCEL_EMA_ALPHA = 0.4


class SmartTracker:
    """Track a smoothed target point and estimate bounded future position."""

    def __init__(self, velocity_ema_alpha: float = 0.45, velocity_deadzone_px_per_s: float = 10.0) -> None:
        self.velocity_ema_alpha = min(max(float(velocity_ema_alpha), 0.0), 1.0)
        self.velocity_deadzone_px_per_s = max(0.0, float(velocity_deadzone_px_per_s))
        self.reset()

    def reset(self) -> None:
        self.last_x: float | None = None
        self.last_y: float | None = None
        self.vx: float = 0.0
        self.vy: float = 0.0
        self.ax: float = 0.0
        self.ay: float = 0.0
        self.update_count: int = 0
        self.initialized: bool = False

    def update(
        self,
        measured_x: float,
        measured_y: float,
        dt: float,
        jump_reset_distance_px: float,
        motion_dx: float | None = None,
        motion_dy: float | None = None,
    ) -> Tuple[float, float]:
        safe_dt = max(float(dt), 1e-4)
        jump_limit = max(float(jump_reset_distance_px), 0.0)

        if not self.initialized:
            self.last_x = measured_x
            self.last_y = measured_y
            self.vx = 0.0
            self.vy = 0.0
            self.ax = 0.0
            self.ay = 0.0
            self.update_count = 1
            self.initialized = True
            return self.vx, self.vy

        previous_vx = self.vx
        previous_vy = self.vy

        measured_dx = measured_x - float(self.last_x)
        measured_dy = measured_y - float(self.last_y)
        resolved_motion_dx = measured_dx if motion_dx is None else float(motion_dx)
        resolved_motion_dy = measured_dy if motion_dy is None else float(motion_dy)
        raw_vx = resolved_motion_dx / safe_dt
        raw_vy = resolved_motion_dy / safe_dt

        dot_product = (raw_vx * self.vx) + (raw_vy * self.vy)
        jump_distance = max(
            math.hypot(measured_dx, measured_dy),
            math.hypot(resolved_motion_dx, resolved_motion_dy),
        )

        reset_velocity = jump_distance >= jump_limit or dot_product < 0.0
        if reset_velocity:
            self.vx = raw_vx
            self.vy = raw_vy
            # A sign flip / jump invalidates any acceleration estimate too.
            self.ax = 0.0
            self.ay = 0.0
        else:
            alpha = self.velocity_ema_alpha
            self.vx = ((1.0 - alpha) * self.vx) + (alpha * raw_vx)
            self.vy = ((1.0 - alpha) * self.vy) + (alpha * raw_vy)

            raw_ax = (self.vx - previous_vx) / safe_dt
            raw_ay = (self.vy - previous_vy) / safe_dt
            raw_ax = max(-_ACCEL_CAP_PX_PER_S2, min(_ACCEL_CAP_PX_PER_S2, raw_ax))
            raw_ay = max(-_ACCEL_CAP_PX_PER_S2, min(_ACCEL_CAP_PX_PER_S2, raw_ay))
            self.ax = ((1.0 - _ACCEL_EMA_ALPHA) * self.ax) + (_ACCEL_EMA_ALPHA * raw_ax)
            self.ay = ((1.0 - _ACCEL_EMA_ALPHA) * self.ay) + (_ACCEL_EMA_ALPHA * raw_ay)

        if abs(self.vx) < self.velocity_deadzone_px_per_s:
            self.vx = 0.0
        if abs(self.vy) < self.velocity_deadzone_px_per_s:
            self.vy = 0.0

        self.last_x = measured_x
        self.last_y = measured_y
        self.update_count += 1
        return self.vx, self.vy

    def get_predicted_position(
        self,
        prediction_time_s: float,
        max_distance_px: float,
        use_acceleration: bool = False,
    ) -> Tuple[float, float]:
        if not self.initialized or self.last_x is None or self.last_y is None:
            return 0.0, 0.0

        pred_dx = self.vx * prediction_time_s
        pred_dy = self.vy * prediction_time_s

        if use_acceleration and self.update_count >= 3:
            t_sq = float(prediction_time_s) * float(prediction_time_s)
            pred_dx += 0.5 * self.ax * t_sq
            pred_dy += 0.5 * self.ay * t_sq

        max_distance = max(0.0, float(max_distance_px))
        predicted_distance = math.hypot(pred_dx, pred_dy)
        if max_distance > 0.0 and predicted_distance > max_distance:
            scale = max_distance / predicted_distance
            pred_dx *= scale
            pred_dy *= scale

        return self.last_x + pred_dx, self.last_y + pred_dy

    def get_speed(self) -> float:
        return math.hypot(self.vx, self.vy)

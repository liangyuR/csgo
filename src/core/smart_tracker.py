"""Motion prediction tracker used by the aim loop."""

from __future__ import annotations

import math
from typing import Tuple


class SmartTracker:
    """Track a smoothed target point and estimate bounded future position."""

    def __init__(self, velocity_ema_alpha: float = 0.35, velocity_deadzone_px_per_s: float = 10.0) -> None:
        self.velocity_ema_alpha = min(max(float(velocity_ema_alpha), 0.0), 1.0)
        self.velocity_deadzone_px_per_s = max(0.0, float(velocity_deadzone_px_per_s))
        self.reset()

    def reset(self) -> None:
        self.last_x: float | None = None
        self.last_y: float | None = None
        self.vx: float = 0.0
        self.vy: float = 0.0
        self.initialized: bool = False

    def update(self, measured_x: float, measured_y: float, dt: float, jump_reset_distance_px: float) -> Tuple[float, float]:
        safe_dt = max(float(dt), 1e-4)
        jump_limit = max(float(jump_reset_distance_px), 0.0)

        if not self.initialized:
            self.last_x = measured_x
            self.last_y = measured_y
            self.vx = 0.0
            self.vy = 0.0
            self.initialized = True
            return self.vx, self.vy

        dx = measured_x - float(self.last_x)
        dy = measured_y - float(self.last_y)
        raw_vx = dx / safe_dt
        raw_vy = dy / safe_dt

        dot_product = (raw_vx * self.vx) + (raw_vy * self.vy)
        jump_distance = math.hypot(dx, dy)

        if jump_distance >= jump_limit or dot_product < 0.0:
            self.vx = raw_vx
            self.vy = raw_vy
        else:
            alpha = self.velocity_ema_alpha
            self.vx = ((1.0 - alpha) * self.vx) + (alpha * raw_vx)
            self.vy = ((1.0 - alpha) * self.vy) + (alpha * raw_vy)

        if abs(self.vx) < self.velocity_deadzone_px_per_s:
            self.vx = 0.0
        if abs(self.vy) < self.velocity_deadzone_px_per_s:
            self.vy = 0.0

        self.last_x = measured_x
        self.last_y = measured_y
        return self.vx, self.vy

    def get_predicted_position(
        self,
        prediction_time_s: float,
        max_distance_px: float,
    ) -> Tuple[float, float]:
        if not self.initialized or self.last_x is None or self.last_y is None:
            return 0.0, 0.0

        pred_dx = self.vx * prediction_time_s
        pred_dy = self.vy * prediction_time_s

        max_distance = max(0.0, float(max_distance_px))
        predicted_distance = math.hypot(pred_dx, pred_dy)
        if max_distance > 0.0 and predicted_distance > max_distance:
            scale = max_distance / predicted_distance
            pred_dx *= scale
            pred_dy *= scale

        return self.last_x + pred_dx, self.last_y + pred_dy

    def get_speed(self) -> float:
        return math.hypot(self.vx, self.vy)

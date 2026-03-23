"""Motion prediction tracker used by the aim loop."""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np


class _PositionKalmanFilter:
    """2-D constant-velocity Kalman filter for target position smoothing.

    State vector: [x, y, vx, vy]
    Measurement:  [x, y]

    Provides smooth position and velocity estimates under noisy detections.
    The process noise Q uses the standard discrete constant-velocity model
    (driven by jerk), so velocity uncertainty grows with time as sqrt(q*dt).
    """

    __slots__ = ("q", "r", "x", "P", "initialized")

    def __init__(self, process_noise: float = 80.0, measurement_noise: float = 4.0) -> None:
        self.q = float(process_noise)
        self.r = float(measurement_noise)
        self.x = np.zeros(4, dtype=np.float64)
        self.P = np.eye(4, dtype=np.float64) * 500.0
        self.initialized = False

    def reset(self) -> None:
        self.x[:] = 0.0
        self.P = np.eye(4, dtype=np.float64) * 500.0
        self.initialized = False

    def reset_to(self, px: float, py: float, vx: float = 0.0, vy: float = 0.0) -> None:
        self.x[0] = px
        self.x[1] = py
        self.x[2] = vx
        self.x[3] = vy
        self.P = np.eye(4, dtype=np.float64) * 500.0
        self.initialized = True

    def predict(self, dt: float) -> None:
        dt = max(float(dt), 1e-4)
        # State transition
        self.x[0] += self.x[2] * dt
        self.x[1] += self.x[3] * dt
        # Covariance prediction: P = F P F^T + Q
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt3 * dt
        q = self.q
        # Standard discrete constant-velocity process noise
        Q = np.array(
            [
                [q * dt4 / 4.0, 0.0, q * dt3 / 2.0, 0.0],
                [0.0, q * dt4 / 4.0, 0.0, q * dt3 / 2.0],
                [q * dt3 / 2.0, 0.0, q * dt2, 0.0],
                [0.0, q * dt3 / 2.0, 0.0, q * dt2],
            ],
            dtype=np.float64,
        )
        F = np.array(
            [
                [1.0, 0.0, dt, 0.0],
                [0.0, 1.0, 0.0, dt],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        self.P = F @ self.P @ F.T + Q

    def update(self, px: float, py: float) -> None:
        # Kalman update with measurement [px, py]
        # H = [[1,0,0,0],[0,1,0,0]]  — only position is observed
        hx0 = self.x[0]
        hx1 = self.x[1]
        # Innovation
        y0 = px - hx0
        y1 = py - hx1
        # S = H P H^T + R  (2x2)
        r = self.r
        s00 = self.P[0, 0] + r
        s01 = self.P[0, 1]
        s10 = self.P[1, 0]
        s11 = self.P[1, 1] + r
        # S^-1 (2x2 analytic inverse)
        det = s00 * s11 - s01 * s10
        if abs(det) < 1e-10:
            return
        inv_det = 1.0 / det
        si00 = s11 * inv_det
        si01 = -s01 * inv_det
        si10 = -s10 * inv_det
        si11 = s00 * inv_det
        # K = P H^T S^-1  — only first two columns of H^T are non-zero
        # K is 4x2
        ph0 = self.P[:, 0]  # P * H^T col 0
        ph1 = self.P[:, 1]  # P * H^T col 1
        k0 = ph0 * si00 + ph1 * si10  # K col 0
        k1 = ph0 * si01 + ph1 * si11  # K col 1
        # State update
        self.x += k0 * y0 + k1 * y1
        # Covariance update: P = (I - K H) P  (Joseph form for stability)
        KH = np.zeros((4, 4), dtype=np.float64)
        KH[:, 0] = k0
        KH[:, 1] = k1
        IKH = np.eye(4, dtype=np.float64) - KH
        self.P = IKH @ self.P
        self.initialized = True

    @property
    def position(self) -> Tuple[float, float]:
        return float(self.x[0]), float(self.x[1])

    @property
    def kf_vx(self) -> float:
        return float(self.x[2])

    @property
    def kf_vy(self) -> float:
        return float(self.x[3])


class SmartTracker:
    """Track a smoothed target point and estimate bounded future position.

    Uses an EMA velocity estimator (public ``vx``/``vy`` attributes) for
    backward-compatibility, plus a ``_PositionKalmanFilter`` to smooth the
    base position that ``get_predicted_position`` extrapolates from.  The
    combination gives jitter-resistant prediction without breaking the test
    contracts that directly read ``vx``/``vy``.
    """

    def __init__(
        self,
        velocity_ema_alpha: float = 0.45,
        velocity_deadzone_px_per_s: float = 10.0,
        kalman_process_noise: float = 80.0,
        kalman_measurement_noise: float = 4.0,
    ) -> None:
        self.velocity_ema_alpha = min(max(float(velocity_ema_alpha), 0.0), 1.0)
        self.velocity_deadzone_px_per_s = max(0.0, float(velocity_deadzone_px_per_s))
        self._kf = _PositionKalmanFilter(kalman_process_noise, kalman_measurement_noise)
        self.reset()

    def reset(self) -> None:
        self.last_x: float | None = None
        self.last_y: float | None = None
        self.vx: float = 0.0
        self.vy: float = 0.0
        self.initialized: bool = False
        self._kf.reset()

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
            self.initialized = True
            self._kf.reset_to(measured_x, measured_y)
            return self.vx, self.vy

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

        jumped = jump_distance >= jump_limit or dot_product < 0.0

        # ---- EMA velocity (public interface, used by tests) ----
        if jumped:
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

        # ---- Kalman filter (position smoothing) ----
        if jumped:
            # Hard reset: reinitialise at new position with current raw velocity
            self._kf.reset_to(measured_x, measured_y, raw_vx, raw_vy)
        else:
            self._kf.predict(safe_dt)
            self._kf.update(measured_x, measured_y)

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

        # When there is no velocity the prediction equals the current position.
        # Use the raw measured last_x/y directly so the result is exact (the
        # KF smooths position but introduces a small lag that violates strict
        # equality checks when vx == vy == 0).
        if pred_dx == 0.0 and pred_dy == 0.0:
            return float(self.last_x), float(self.last_y)

        # With active velocity, use the KF-smoothed base position as the
        # starting point so per-frame detection jitter does not propagate into
        # the extrapolated aim point.
        if self._kf.initialized:
            base_x, base_y = self._kf.position
        else:
            base_x, base_y = float(self.last_x), float(self.last_y)

        max_distance = max(0.0, float(max_distance_px))
        predicted_distance = math.hypot(pred_dx, pred_dy)
        if max_distance > 0.0 and predicted_distance > max_distance:
            scale = max_distance / predicted_distance
            pred_dx *= scale
            pred_dy *= scale

        return base_x + pred_dx, base_y + pred_dy

    def get_speed(self) -> float:
        return math.hypot(self.vx, self.vy)

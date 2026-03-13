"""Aim smoothing, FOV gating, deadzone, and max-speed clamping.

Responsibilities:
1. FOV gate      — ignore targets farther than *fov_radius* pixels from the
                   screen centre.  Prevents wild mouse swings when a player
                   runs across the far edge of the screen.
2. Deadzone      — return (0, 0) when the target is already within *deadzone_pixels*
                   of the crosshair.  Avoids micro-jitter once locked on.
3. Lerp smoother — move a fixed fraction of the remaining offset each tick,
                   producing natural-looking continuous movement rather than
                   a one-frame snap.
4. Max-speed cap — clamp the per-tick step vector to *max_speed* pixels so that
                   even a large sudden offset only moves the mouse at a controlled
                   rate, preventing rubber-banding or overshoot.
5. Sub-pixel accumulation — carry the fractional remainder across frames so that
                   small offsets are not permanently lost to integer rounding.

Return-value conventions (from `compute`):
  None        → target is outside the FOV gate; caller must not move the mouse.
  (0, 0)      → target is inside the deadzone; already acquired, no move needed.
  (dx, dy)    → non-zero relative mouse movement to send this tick.
"""
from __future__ import annotations

from math import sqrt
from typing import Optional


class AimSmoother:
    """Lerp aim smoother with FOV gate, deadzone, and per-tick speed cap.

    Args:
        fov_radius:       Maximum pixel distance from screen centre to consider
                          a target valid.  Targets outside this circle are
                          ignored and *compute* returns None.
        smoothing:        Lerp factor in (0, 1].  1.0 = instant snap to target;
                          0.3 = move 30 % of remaining offset per tick.
        deadzone_pixels:  If the target is within this many pixels of the
                          crosshair, *compute* returns (0, 0) — the aim is
                          already acquired, no movement is sent.
        max_speed:        Hard upper bound on the per-tick mouse delta magnitude
                          (pixels).  The step vector is normalised and scaled
                          down when it would exceed this value.
    """

    def __init__(
        self,
        fov_radius: float = 200.0,
        smoothing: float = 0.4,
        deadzone_pixels: float = 3.0,
        max_speed: float = 30.0,
    ) -> None:
        if not 0.0 < smoothing <= 1.0:
            raise ValueError(f"smoothing must be in (0, 1], got {smoothing}")
        self.fov_radius = float(fov_radius)
        self.smoothing = float(smoothing)
        self.deadzone_pixels = max(0.0, float(deadzone_pixels))
        self.max_speed = max(1.0, float(max_speed))

        # Accumulated fractional sub-pixel remainder from previous frames so
        # we don't permanently lose small offsets due to integer rounding.
        self._remainder_x: float = 0.0
        self._remainder_y: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear accumulated sub-pixel remainder (call when target is lost)."""
        self._remainder_x = 0.0
        self._remainder_y = 0.0

    def compute(
        self,
        offset_x: float,
        offset_y: float,
    ) -> Optional[tuple[int, int]]:
        """Return the integer (dx, dy) mouse delta to send this tick.

        Returns:
            None     — target outside FOV gate; caller should not move the mouse
                       and should treat the target as invalid.
            (0, 0)   — target inside deadzone; crosshair already acquired.
            (dx, dy) — non-zero delta to apply via SendInput this tick.

        Args:
            offset_x: Horizontal distance from screen centre to aim point
                      (positive = aim point is to the right of crosshair).
            offset_y: Vertical distance from screen centre to aim point
                      (positive = aim point is below crosshair).
        """
        distance = sqrt(offset_x * offset_x + offset_y * offset_y)

        # --- FOV gate: target too far from crosshair ---
        if distance > self.fov_radius:
            self.reset()
            return None

        # --- Deadzone: already on target ---
        if distance <= self.deadzone_pixels:
            self.reset()
            return 0, 0

        # --- Lerp: move a fraction of the remaining offset ---
        smooth_x = offset_x * self.smoothing + self._remainder_x
        smooth_y = offset_y * self.smoothing + self._remainder_y

        # --- Max-speed clamp: limit per-tick movement magnitude ---
        step_len = sqrt(smooth_x * smooth_x + smooth_y * smooth_y)
        if step_len > self.max_speed:
            scale = self.max_speed / step_len
            smooth_x *= scale
            smooth_y *= scale

        # Convert to integers, carry sub-pixel remainder forward.
        int_x = int(smooth_x)
        int_y = int(smooth_y)
        self._remainder_x = smooth_x - int_x
        self._remainder_y = smooth_y - int_y

        return int_x, int_y

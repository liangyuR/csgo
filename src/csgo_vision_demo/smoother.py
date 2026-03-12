"""Aim smoothing and FOV gating module.

Two responsibilities:
1. FOV gate  -- ignore targets whose aim point is farther than `fov_radius`
   pixels from the screen centre.  Prevents wild mouse swings.
2. Lerp smoother -- instead of teleporting the crosshair to the target in one
   frame, move a fixed fraction of the remaining offset each frame.  This
   produces natural-looking, continuous mouse movement.
"""
from __future__ import annotations

from math import sqrt
from typing import Optional


class AimSmoother:
    """Linear-interpolation aim smoother with FOV-radius gating.

    Args:
        fov_radius:  Maximum pixel distance from screen centre to consider a
            target valid.  Targets outside this circle are ignored.
        smoothing:   Lerp factor in (0, 1].  1.0 = instant snap; 0.3 = move
            30 % of remaining offset per frame.
    """

    def __init__(self, fov_radius: float = 200.0, smoothing: float = 0.4) -> None:
        if not 0.0 < smoothing <= 1.0:
            raise ValueError(f"smoothing must be in (0, 1], got {smoothing}")
        self.fov_radius = float(fov_radius)
        self.smoothing = float(smoothing)

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
        """Return integer (dx, dy) to send to the mouse controller.

        Returns None if the target is outside the FOV gate (caller should not
        move the mouse at all in this case).

        Args:
            offset_x: Horizontal distance from screen centre to aim point
                (positive = right).
            offset_y: Vertical distance from screen centre to aim point
                (positive = down).
        """
        distance = sqrt(offset_x * offset_x + offset_y * offset_y)
        if distance > self.fov_radius:
            self.reset()
            return None

        # Apply lerp to the raw offset, then accumulate sub-pixel remainder.
        smooth_x = offset_x * self.smoothing + self._remainder_x
        smooth_y = offset_y * self.smoothing + self._remainder_y

        int_x = int(smooth_x)
        int_y = int(smooth_y)

        self._remainder_x = smooth_x - int_x
        self._remainder_y = smooth_y - int_y

        return int_x, int_y

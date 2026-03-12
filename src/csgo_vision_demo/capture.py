"""Screen capture module for real-time game frame acquisition.

Supports two modes:
- full: capture the entire primary monitor
- center_crop: capture a square region centered on the screen (better inference speed)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class CaptureConfig:
    method: str = "mss"
    region: str = "full"          # "full" | "center_crop"
    center_crop_size: int = 640   # pixels, used when region == "center_crop"
    monitor_index: int = 1        # mss monitor index (1 = primary)


class ScreenCapture:
    """Real-time screen capture using mss.

    Usage:
        cap = ScreenCapture(CaptureConfig(...))
        with cap:
            frame = cap.grab()   # numpy BGR array, ready for OpenCV / YOLO
    """

    def __init__(self, config: CaptureConfig | None = None) -> None:
        self.config = config or CaptureConfig()
        self._sct = None
        self._monitor: Optional[dict] = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "ScreenCapture":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        try:
            import mss
        except ImportError as exc:
            raise RuntimeError(
                "mss is not installed. Run: pip install mss"
            ) from exc

        self._sct = mss.mss()
        self._monitor = self._build_monitor()

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def grab(self) -> np.ndarray:
        """Capture one frame and return a BGR numpy array."""
        if self._sct is None:
            raise RuntimeError("ScreenCapture is not open. Use 'with ScreenCapture()' or call open().")

        raw = self._sct.grab(self._monitor)
        # mss returns BGRA; drop alpha channel → BGR
        frame = np.array(raw, dtype=np.uint8)[:, :, :3]
        return frame

    @property
    def region(self) -> dict:
        """Return the current monitor region dict."""
        if self._monitor is None:
            raise RuntimeError("ScreenCapture is not open.")
        return dict(self._monitor)

    @property
    def width(self) -> int:
        return self._monitor["width"] if self._monitor else 0

    @property
    def height(self) -> int:
        return self._monitor["height"] if self._monitor else 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_monitor(self) -> dict:
        monitors = self._sct.monitors  # index 0 = virtual screen; 1+ = physical
        idx = max(0, min(self.config.monitor_index, len(monitors) - 1))
        mon = monitors[idx]

        if self.config.region == "full":
            return dict(mon)

        if self.config.region == "center_crop":
            size = self.config.center_crop_size
            cx = mon["left"] + mon["width"] // 2
            cy = mon["top"] + mon["height"] // 2
            half = size // 2
            return {
                "left": cx - half,
                "top": cy - half,
                "width": size,
                "height": size,
                "mon": idx,
            }

        raise ValueError(f"Unknown capture region mode: {self.config.region!r}")

"""Screen capture backends for AI inference."""

from __future__ import annotations

import logging
import sys
from typing import Dict

import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)

try:
    if sys.platform == "win32":
        import dxcam  # type: ignore[import-not-found]
    else:
        dxcam = None
except ImportError:
    dxcam = None


CaptureRegion = Dict[str, int]


class ScreenCaptureBackend:
    name = "unknown"

    def grab(self, region: CaptureRegion) -> npt.NDArray[np.uint8] | None:
        raise NotImplementedError

    def close(self) -> None:
        return


class DXCamCaptureBackend(ScreenCaptureBackend):
    name = "dxcam"

    def __init__(self) -> None:
        if dxcam is None:
            raise RuntimeError("dxcam is not available")

        self._camera = dxcam.create(output_color="RGB")
        if self._camera is None:
            raise RuntimeError("dxcam.create returned no camera instance")

    def grab(self, region: CaptureRegion) -> npt.NDArray[np.uint8] | None:
        left = int(region["left"])
        top = int(region["top"])
        right = left + int(region["width"])
        bottom = top + int(region["height"])
        frame = self._camera.grab(region=(left, top, right, bottom))
        if frame is None:
            return None
        if frame.dtype != np.uint8:
            frame = frame.astype(np.uint8, copy=False)
        if not frame.flags.c_contiguous:
            return np.ascontiguousarray(frame)
        return frame

    def close(self) -> None:
        stop = getattr(self._camera, "stop", None)
        if callable(stop):
            stop()
        release = getattr(self._camera, "release", None)
        if callable(release):
            release()


def create_capture_backend(preference: str = "auto") -> ScreenCaptureBackend:
    selected = str(preference or "auto").lower()

    if selected in {"auto", "dxcam"}:
        try:
            backend = DXCamCaptureBackend()
            logger.info("Using screen capture backend: %s", backend.name)
            return backend
        except Exception as e:
            raise RuntimeError(f"dxcam capture backend is unavailable: {e}") from e

    raise RuntimeError(f"Unsupported capture backend: {selected}")

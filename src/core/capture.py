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
    """DXCam backend running in continuous mode.

    DXCam's internal thread captures the full screen at up to target_fps.
    grab() reads the latest buffered frame non-blocking and crops to the
    requested region via a numpy slice — eliminating the per-call blocking
    wait on the Desktop Duplication API that snapshot mode incurs.
    """

    name = "dxcam"

    def __init__(self) -> None:
        if dxcam is None:
            raise RuntimeError("dxcam is not available")

        self._camera = dxcam.create(output_color="RGB")
        if self._camera is None:
            raise RuntimeError("dxcam.create returned no camera instance")

        # Start continuous full-screen capture; video_mode=False means
        # get_latest_frame() returns immediately even if no new frame arrived.
        try:
            self._camera.start(target_fps=240, video_mode=False)
            self._continuous = True
        except Exception as e:
            logger.warning("DXCam continuous mode unavailable (%s), using snapshot mode", e)
            self._continuous = False

        self._last_full_frame: npt.NDArray[np.uint8] | None = None

    def grab(self, region: CaptureRegion) -> npt.NDArray[np.uint8] | None:
        if self._continuous:
            full = self._camera.get_latest_frame()
            if full is None:
                full = self._last_full_frame
            if full is None:
                return None
            self._last_full_frame = full

            left = int(region["left"])
            top = int(region["top"])
            right = left + int(region["width"])
            bottom = top + int(region["height"])

            h, w = full.shape[:2]
            top = max(0, min(top, h))
            bottom = max(top, min(bottom, h))
            left = max(0, min(left, w))
            right = max(left, min(right, w))

            cropped = full[top:bottom, left:right]
            if cropped.size == 0:
                return None
            if cropped.dtype != np.uint8:
                cropped = cropped.astype(np.uint8, copy=False)
            if not cropped.flags.c_contiguous:
                return np.ascontiguousarray(cropped)
            return cropped
        else:
            # Fallback: snapshot mode
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
        if self._continuous:
            stop = getattr(self._camera, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        release = getattr(self._camera, "release", None)
        if callable(release):
            try:
                release()
            except Exception:
                pass


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

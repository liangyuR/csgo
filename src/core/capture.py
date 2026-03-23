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
    """DXCam backend using continuous ROI capture.

    On the first ``grab()`` call the camera is started in continuous mode
    with the requested region passed directly to DXCam.  Subsequent calls
    return the latest buffered frame via ``get_latest_frame()`` which never
    blocks on the Desktop Duplication API.

    If the region ever changes (e.g. detection size config update) the camera
    is restarted automatically with the new region.

    This is the optimal strategy when the detection window is fixed (i.e.
    ``fov_follow_mouse=False``): DXCam's internal thread captures only the
    ~640×640 ROI, keeping memory bandwidth minimal (~1.2 MB/frame vs ~24 MB
    for full 4K), while the AI loop never blocks waiting for the next frame.
    """

    name = "dxcam"

    def __init__(self) -> None:
        if dxcam is None:
            raise RuntimeError("dxcam is not available")

        self._camera = dxcam.create(output_color="RGB")
        if self._camera is None:
            raise RuntimeError("dxcam.create returned no camera instance")

        self._active_ltrb: tuple[int, int, int, int] | None = None

    def _start(self, ltrb: tuple[int, int, int, int]) -> None:
        stop = getattr(self._camera, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass
        self._camera.start(target_fps=240, video_mode=False, region=ltrb)
        self._active_ltrb = ltrb
        logger.debug("DXCam started with ROI %s", ltrb)

    def grab(self, region: CaptureRegion) -> npt.NDArray[np.uint8] | None:
        left = int(region["left"])
        top = int(region["top"])
        right = left + int(region["width"])
        bottom = top + int(region["height"])
        ltrb = (left, top, right, bottom)

        if ltrb != self._active_ltrb:
            self._start(ltrb)

        frame = self._camera.get_latest_frame()
        if frame is None:
            return None
        if frame.dtype != np.uint8:
            frame = frame.astype(np.uint8, copy=False)
        if not frame.flags.c_contiguous:
            frame = np.ascontiguousarray(frame)
        return frame

    def close(self) -> None:
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

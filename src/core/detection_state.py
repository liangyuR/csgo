"""Shared detection payload and latest-frame state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float32]
IntArray = npt.NDArray[np.int32]


def _as_float_array(value: Any, shape: tuple[int, ...]) -> FloatArray:
    array = np.asarray(value, dtype=np.float32)
    if array.size == 0:
        if len(shape) == 2:
            result = np.empty((0, shape[1]), dtype=np.float32)
        else:
            result = np.empty((0,), dtype=np.float32)
    elif array.shape == shape:
        result = array
    else:
        result = np.reshape(array, shape)
    result.setflags(write=False)
    return result


def _as_int_array(value: Any) -> IntArray:
    array = np.asarray(value, dtype=np.int32)
    if array.ndim == 0:
        array = array.reshape((1,))
    elif array.size == 0:
        array = np.empty((0,), dtype=np.int32)
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class DetectionPayload:
    boxes: FloatArray
    confidences: FloatArray
    class_ids: IntArray

    def __post_init__(self) -> None:
        object.__setattr__(self, "boxes", _as_float_array(self.boxes, (-1, 4)))
        object.__setattr__(self, "confidences", _as_float_array(self.confidences, (-1,)))
        object.__setattr__(self, "class_ids", _as_int_array(self.class_ids))

    def has_boxes(self) -> bool:
        return self.boxes.shape[0] > 0


@dataclass(frozen=True)
class DetectionFrame:
    sequence: int
    captured_perf: float
    crosshair_x: int
    crosshair_y: int
    aiming_active: bool
    payload: DetectionPayload


class LatestDetectionState:
    """Container that always exposes the newest detection frame."""

    def __init__(self) -> None:
        self._frame: DetectionFrame | None = None

    def publish(self, frame: DetectionFrame) -> None:
        self._frame = frame

    def snapshot(self) -> DetectionFrame | None:
        return self._frame


def empty_detection_payload() -> DetectionPayload:
    return DetectionPayload(
        np.empty((0, 4), dtype=np.float32),
        np.empty((0,), dtype=np.float32),
        np.empty((0,), dtype=np.int32),
    )

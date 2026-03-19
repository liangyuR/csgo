"""Shared detection payload and latest-frame state."""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class DetectionPayload:
    boxes: list[list[float]]
    confidences: list[float]
    class_ids: list[int]


@dataclass(frozen=True)
class DetectionFrame:
    sequence: int
    captured_perf: float
    crosshair_x: int
    crosshair_y: int
    aiming_active: bool
    payload: DetectionPayload


class LatestDetectionState:
    """Thread-safe container that always exposes the newest detection frame."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: DetectionFrame | None = None

    def publish(self, frame: DetectionFrame) -> None:
        with self._lock:
            self._frame = frame

    def snapshot(self) -> DetectionFrame | None:
        with self._lock:
            return self._frame


def empty_detection_payload() -> DetectionPayload:
    return DetectionPayload([], [], [])

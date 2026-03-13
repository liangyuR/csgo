"""Geometry utilities for aim-point extraction and screen-offset calculation.

Coordinate system convention (same as mss screen captures):
  - Origin (0, 0) is the top-left corner of the captured region.
  - x increases to the right, y increases downward.
  - Screen center == (frame_width / 2, frame_height / 2).
  - offset_x = aim_point_x - center_x  (positive → aim is right of crosshair)
  - offset_y = aim_point_y - center_y  (positive → aim is below crosshair)

Aim-point selection priority (pose_head mode):
  1. Nose keypoint (index 0) — most reliable single-point head indicator.
  2. Eyes midpoint (indices 1, 2) — fallback when nose is occluded.
  3. Ears midpoint (indices 3, 4) — last resort before bbox fallback.
  4. Bbox upper_center — used when no keypoint clears the confidence threshold.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable, Sequence


@dataclass(frozen=True)
class DetectionGeometry:
    bbox: tuple[float, float, float, float]
    aim_point: tuple[float, float]
    offset: tuple[float, float]
    distance_to_center: float


HEAD_KEYPOINT_PRIORITY = (
    ("nose", (0,)),
    ("eyes_midpoint", (1, 2)),
    ("ears_midpoint", (3, 4)),
)


def compute_aim_point(
    bbox: Sequence[float],
    mode: str = "center",
    head_fraction: float = 0.18,
) -> tuple[float, float]:
    x1, y1, x2, y2 = [float(v) for v in bbox]
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    center_x = x1 + width / 2.0

    if mode == "center":
        center_y = y1 + height / 2.0
        return center_x, center_y
    if mode == "upper_center":
        return center_x, y1 + (height * max(0.0, min(head_fraction, 1.0)))
    if mode == "pose_head":
        return center_x, y1 + (height * max(0.0, min(head_fraction, 1.0)))

    raise ValueError(f"Unsupported aim mode: {mode}")


def extract_pose_head_point(
    keypoints: Sequence[Sequence[float]] | None,
    confidences: Sequence[float] | None = None,
    min_confidence: float = 0.0,
) -> tuple[tuple[float, float], str] | None:
    if not keypoints:
        return None

    def get_point(index: int) -> tuple[float, float] | None:
        if index >= len(keypoints):
            return None
        point = keypoints[index]
        if len(point) < 2:
            return None
        x = float(point[0])
        y = float(point[1])
        if confidences is not None:
            if index >= len(confidences) or float(confidences[index]) < min_confidence:
                return None
        if x <= 0.0 and y <= 0.0:
            return None
        return x, y

    for source, indices in HEAD_KEYPOINT_PRIORITY:
        points = [point for idx in indices if (point := get_point(idx)) is not None]
        if len(points) != len(indices):
            continue
        mean_x = sum(point[0] for point in points) / len(points)
        mean_y = sum(point[1] for point in points) / len(points)
        return (mean_x, mean_y), source

    return None


def build_detection_geometry(
    bbox: Sequence[float],
    frame_size: Sequence[int],
    mode: str = "center",
    head_fraction: float = 0.18,
    aim_point: Sequence[float] | None = None,
) -> DetectionGeometry:
    frame_width, frame_height = int(frame_size[0]), int(frame_size[1])
    screen_center = (frame_width / 2.0, frame_height / 2.0)
    if aim_point is None:
        aim_x, aim_y = compute_aim_point(bbox, mode=mode, head_fraction=head_fraction)
    else:
        aim_x, aim_y = float(aim_point[0]), float(aim_point[1])

    # Clamp aim point to frame bounds so out-of-frame YOLO keypoints (which
    # can occasionally appear slightly outside the image) never produce a
    # wildly large offset that slams the crosshair across the screen.
    aim_x = max(0.0, min(float(frame_width), aim_x))
    aim_y = max(0.0, min(float(frame_height), aim_y))

    offset_x = aim_x - screen_center[0]
    offset_y = aim_y - screen_center[1]
    distance = sqrt((offset_x * offset_x) + (offset_y * offset_y))
    return DetectionGeometry(
        bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
        aim_point=(aim_x, aim_y),
        offset=(offset_x, offset_y),
        distance_to_center=distance,
    )


def select_primary_index(geometries: Iterable[DetectionGeometry]) -> int | None:
    items = list(geometries)
    if not items:
        return None
    ranked = sorted(enumerate(items), key=lambda item: item[1].distance_to_center)
    return ranked[0][0]

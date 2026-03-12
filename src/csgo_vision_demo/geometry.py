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

    raise ValueError(f"Unsupported aim mode: {mode}")


def build_detection_geometry(
    bbox: Sequence[float],
    frame_size: Sequence[int],
    mode: str = "center",
    head_fraction: float = 0.18,
) -> DetectionGeometry:
    frame_width, frame_height = int(frame_size[0]), int(frame_size[1])
    screen_center = (frame_width / 2.0, frame_height / 2.0)
    aim_x, aim_y = compute_aim_point(bbox, mode=mode, head_fraction=head_fraction)
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

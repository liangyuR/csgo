from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .geometry import build_detection_geometry, extract_pose_head_point, select_primary_index


@dataclass
class DetectionRecord:
    source_file: str
    frame_index: int
    class_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
    aim_x: float
    aim_y: float
    offset_x: float
    offset_y: float
    distance_to_center: float
    is_primary_target: bool
    aim_source: str


def list_model_classes(model) -> dict[int, str]:
    names = model.names
    if isinstance(names, dict):
        return {int(k): str(v) for k, v in names.items()}
    return {idx: str(name) for idx, name in enumerate(names)}


def extract_detection_records(
    result,
    frame_shape: Sequence[int],
    class_names: dict[int, str],
    target_class_names: set[str] | None = None,
    target_class_ids: set[int] | None = None,
    aim_mode: str = "center",
    target_strategy: str = "nearest_head_to_center",
    min_keypoint_confidence: float = 0.35,
    head_fraction: float = 0.18,
) -> tuple[list[DetectionRecord], int | None]:
    height, width = int(frame_shape[0]), int(frame_shape[1])
    target_class_names = target_class_names or set()
    target_class_ids = target_class_ids or set()
    detections: list[DetectionRecord] = []
    geometries = []

    if getattr(result, "boxes", None) is None:
        return detections, None

    xyxy = result.boxes.xyxy.cpu().tolist()
    confs = result.boxes.conf.cpu().tolist()
    classes = result.boxes.cls.cpu().tolist()
    keypoint_rows, keypoint_conf_rows = _extract_keypoint_rows(result)

    for index, (bbox, conf, cls) in enumerate(zip(xyxy, confs, classes)):
        class_id = int(cls)
        class_name = class_names.get(class_id, str(class_id))
        if not _class_allowed(class_id, class_name, target_class_names, target_class_ids):
            continue

        pose_aim = None
        if aim_mode == "pose_head" and index < len(keypoint_rows):
            row_conf = keypoint_conf_rows[index] if index < len(keypoint_conf_rows) else None
            pose_aim = extract_pose_head_point(
                keypoint_rows[index],
                row_conf,
                min_confidence=min_keypoint_confidence,
            )

        aim_point = None
        aim_source = "bbox_center" if aim_mode == "center" else "upper_center_fallback"
        if pose_aim is not None:
            aim_point, aim_source = pose_aim

        geometry = build_detection_geometry(
            bbox=bbox,
            frame_size=(width, height),
            mode=aim_mode,
            head_fraction=head_fraction,
            aim_point=aim_point,
        )
        geometries.append(geometry)
        detections.append(
            DetectionRecord(
                source_file="",
                frame_index=0,
                class_id=class_id,
                class_name=class_name,
                confidence=float(conf),
                x1=float(bbox[0]),
                y1=float(bbox[1]),
                x2=float(bbox[2]),
                y2=float(bbox[3]),
                aim_x=float(geometry.aim_point[0]),
                aim_y=float(geometry.aim_point[1]),
                offset_x=float(geometry.offset[0]),
                offset_y=float(geometry.offset[1]),
                distance_to_center=float(geometry.distance_to_center),
                is_primary_target=False,
                aim_source=aim_source,
            )
        )

    primary_index = _select_primary_index(geometries, target_strategy)
    if primary_index is not None:
        detections[primary_index].is_primary_target = True
    return detections, primary_index


def _select_primary_index(geometries, target_strategy: str) -> int | None:
    if target_strategy != "nearest_head_to_center":
        raise ValueError(f"Unsupported target strategy: {target_strategy}")
    return select_primary_index(geometries)


def _class_allowed(
    class_id: int,
    class_name: str,
    target_class_names: set[str],
    target_class_ids: set[int],
) -> bool:
    has_filter = bool(target_class_names or target_class_ids)
    if not has_filter:
        return True
    return class_id in target_class_ids or class_name in target_class_names


def _extract_keypoint_rows(result) -> tuple[list[list[list[float]]], list[list[float] | None]]:
    keypoints = getattr(result, "keypoints", None)
    if keypoints is None or getattr(keypoints, "xy", None) is None:
        return [], []
    xy_rows = keypoints.xy.cpu().tolist()
    conf = getattr(keypoints, "conf", None)
    if conf is None:
        return xy_rows, [None for _ in xy_rows]
    return xy_rows, conf.cpu().tolist()

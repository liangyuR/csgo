"""Ultralytics-backed engine loading and inference helpers."""

from __future__ import annotations

import importlib
from typing import Any

import numpy as np

from .detection_state import DetectionPayload, empty_detection_payload


EMPTY_DETECTION_PAYLOAD = empty_detection_payload()

class UltralyticsEngineModel:
    """Thin Ultralytics wrapper with a stable detect() interface."""

    provider_name = "Ultralytics/TensorRT"

    def __init__(self, engine_path: str, input_size: int) -> None:
        self.engine_path = engine_path
        self.input_size = int(input_size)
        ultralytics_module = self._import_required_module("ultralytics")
        self._model = ultralytics_module.YOLO(engine_path, task="detect")

    def warmup(self, iterations: int = 3) -> None:
        warmup_frame = self._build_warmup_frame()
        for _ in range(max(1, int(iterations))):
            self.detect(warmup_frame, min_confidence=0.0)

    def detect(
        self,
        frame: Any,
        min_confidence: float,
        offset_x: int = 0,
        offset_y: int = 0,
        target_class_id: int | None = None,
        fov_bounds: tuple[int, int, int, int] | None = None,
    ) -> DetectionPayload:
        results = self._model.predict(
            source=frame,
            imgsz=self.input_size,
            conf=float(min_confidence),
            verbose=False,
        )
        if not results:
            return EMPTY_DETECTION_PAYLOAD

        boxes = getattr(results[0], "boxes", None)
        if boxes is None:
            return EMPTY_DETECTION_PAYLOAD

        xyxy = self._to_numpy(getattr(boxes, "xyxy", None))
        confidences = self._to_numpy(getattr(boxes, "conf", None))
        class_ids = self._to_numpy(getattr(boxes, "cls", None))
        if xyxy is None or confidences is None or class_ids is None:
            return EMPTY_DETECTION_PAYLOAD

        xyxy = np.asarray(xyxy, dtype=np.float32)
        confidences = np.asarray(confidences, dtype=np.float32)
        class_ids = np.asarray(class_ids, dtype=np.int32)
        if xyxy.size == 0 or confidences.size == 0 or class_ids.size == 0:
            return EMPTY_DETECTION_PAYLOAD

        keep_mask = np.ones(len(xyxy), dtype=bool)
        if target_class_id is not None:
            keep_mask &= class_ids == int(target_class_id)

        if fov_bounds is not None:
            fov_left, fov_top, fov_right, fov_bottom = fov_bounds
            keep_mask &= (
                (xyxy[:, 0] + offset_x < fov_right)
                & (xyxy[:, 2] + offset_x > fov_left)
                & (xyxy[:, 1] + offset_y < fov_bottom)
                & (xyxy[:, 3] + offset_y > fov_top)
            )

        if not np.any(keep_mask):
            return EMPTY_DETECTION_PAYLOAD

        filtered_boxes = xyxy[keep_mask]
        filtered_confidences = confidences[keep_mask]
        filtered_class_ids = class_ids[keep_mask]

        if offset_x != 0 or offset_y != 0:
            filtered_boxes = filtered_boxes.copy()
            filtered_boxes[:, [0, 2]] += float(offset_x)
            filtered_boxes[:, [1, 3]] += float(offset_y)

        return DetectionPayload(
            boxes=filtered_boxes,
            confidences=filtered_confidences,
            class_ids=filtered_class_ids,
        )

    def _build_warmup_frame(self):
        return np.zeros((self.input_size, self.input_size, 3), dtype=np.uint8)

    @staticmethod
    def _import_required_module(module_name: str):
        try:
            return importlib.import_module(module_name)
        except ImportError as exc:
            raise RuntimeError(
                f"Ultralytics runtime dependency '{module_name}' failed to load. "
                f"Original error: {exc.__class__.__name__}: {exc}"
            ) from exc

    @staticmethod
    def _to_numpy(value: Any):
        if value is None:
            return None
        if hasattr(value, "cpu"):
            value = value.cpu()
        if hasattr(value, "numpy"):
            return value.numpy()
        return value

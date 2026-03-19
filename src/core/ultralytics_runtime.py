"""Ultralytics-backed engine loading and inference helpers."""

from __future__ import annotations

import importlib
import sys
from typing import Any

from .detection_state import DetectionPayload
from ultralytics import YOLO
import numpy as np

class UltralyticsEngineModel:
    """Thin Ultralytics wrapper with a stable detect() interface."""

    provider_name = "Ultralytics/TensorRT"

    def __init__(self, engine_path: str, input_size: int) -> None:
        self.engine_path = engine_path
        self.input_size = int(input_size)
        self._model = YOLO(engine_path, task="detect")

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
    ) -> DetectionPayload:
        results = self._model.predict(
            source=frame,
            imgsz=self.input_size,
            conf=float(min_confidence),
            verbose=False,
        )
        if not results:
            return DetectionPayload([], [], [])

        boxes = getattr(results[0], "boxes", None)
        if boxes is None:
            return DetectionPayload([], [], [])

        xyxy = self._to_numpy(getattr(boxes, "xyxy", None))
        confidences = self._to_numpy(getattr(boxes, "conf", None))
        class_ids = self._to_numpy(getattr(boxes, "cls", None))
        if xyxy is None or confidences is None or class_ids is None:
            return DetectionPayload([], [], [])

        payload_boxes = [
            [
                float(box[0]) + offset_x,
                float(box[1]) + offset_y,
                float(box[2]) + offset_x,
                float(box[3]) + offset_y,
            ]
            for box in xyxy.tolist()
        ]
        return DetectionPayload(
            boxes=payload_boxes,
            confidences=[float(value) for value in confidences.tolist()],
            class_ids=[int(value) for value in class_ids.tolist()],
        )

    def _build_warmup_frame(self):
        return np.zeros((self.input_size, self.input_size, 3), dtype=np.uint8)

    @staticmethod
    def _to_numpy(value: Any):
        if value is None:
            return None
        if hasattr(value, "cpu"):
            value = value.cpu()
        if hasattr(value, "numpy"):
            return value.numpy()
        return value

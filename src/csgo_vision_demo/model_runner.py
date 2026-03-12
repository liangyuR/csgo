from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any


@dataclass
class ModelRunResult:
    result: Any | None
    inference_ms: float
    error: str | None


class ModelRunner:
    def __init__(
        self,
        model_path: str | Path,
        confidence: float = 0.35,
        imgsz: int = 640,
        device: str | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        self.confidence = float(confidence)
        self.imgsz = int(imgsz)
        self.device = device
        self._model = None
        self.loaded = False
        self.last_error: str | None = None
        self.last_inference_ms: float = 0.0
        self.last_success_at: float = 0.0
        self.failure_count = 0

    @property
    def model(self):
        if self._model is None:
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise RuntimeError(
                    "ultralytics is not installed. Run: pip install -r requirements.txt"
                ) from exc
            self._model = YOLO(str(self.model_path))
            self.loaded = True
            self.last_error = None
        return self._model

    def warmup(self, frame) -> None:
        _ = self.predict(frame)

    def predict(self, frame) -> ModelRunResult:
        started = time.perf_counter()
        try:
            result = self.model.predict(
                source=frame,
                conf=self.confidence,
                imgsz=self.imgsz,
                device=self.device,
                verbose=False,
            )[0]
        except Exception as exc:
            self.failure_count += 1
            self.last_error = str(exc)
            self.last_inference_ms = (time.perf_counter() - started) * 1000.0
            return ModelRunResult(result=None, inference_ms=self.last_inference_ms, error=self.last_error)

        self.last_inference_ms = (time.perf_counter() - started) * 1000.0
        self.last_success_at = time.perf_counter()
        self.last_error = None
        return ModelRunResult(result=result, inference_ms=self.last_inference_ms, error=None)

import importlib
import os
import sys
import types
import unittest
from unittest import mock

import numpy as np


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


from core.detection_state import DetectionPayload
from core.ultralytics_runtime import UltralyticsEngineModel


class _FakeTensor:
    def __init__(self, values):
        self._values = np.array(values, dtype=np.float32)

    def cpu(self):
        return self

    def numpy(self):
        return self._values


class _FakeBoxes:
    def __init__(self):
        self.xyxy = _FakeTensor([[10.0, 20.0, 30.0, 40.0], [50.0, 60.0, 70.0, 80.0]])
        self.conf = _FakeTensor([0.9, 0.8])
        self.cls = _FakeTensor([1.0, 3.0])


class _FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class _FakeYOLO:
    def __init__(self, engine_path: str, task: str | None = None):
        self.engine_path = engine_path
        self.task = task
        self.predict_calls = []

    def predict(self, **kwargs):
        self.predict_calls.append(kwargs)
        return [_FakeResult(_FakeBoxes())]


class UltralyticsRuntimeTests(unittest.TestCase):
    def test_missing_dependency_raises_actionable_error(self) -> None:
        real_import_module = importlib.import_module

        def fake_import_module(name: str):
            if name == "ultralytics":
                raise ImportError("missing ultralytics")
            return real_import_module(name)

        instance = UltralyticsEngineModel.__new__(UltralyticsEngineModel)
        with mock.patch("core.ultralytics_runtime.importlib.import_module", side_effect=fake_import_module):
            with self.assertRaises(RuntimeError) as context:
                instance._import_required_module("ultralytics")

        self.assertIn("Ultralytics runtime dependency 'ultralytics' failed to load", str(context.exception))
        self.assertIn("Original error: ImportError: missing ultralytics", str(context.exception))

    def test_detect_loads_engine_via_official_yolo_entrypoint(self) -> None:
        fake_module = types.SimpleNamespace(YOLO=_FakeYOLO)

        with mock.patch("core.ultralytics_runtime.importlib.import_module", return_value=fake_module):
            model = UltralyticsEngineModel("Model/test.engine", input_size=640)

        payload = model.detect(np.zeros((32, 32, 3), dtype=np.uint8), min_confidence=0.25, offset_x=5, offset_y=7)

        self.assertIsInstance(payload, DetectionPayload)
        self.assertEqual(payload.boxes, [[15.0, 27.0, 35.0, 47.0], [55.0, 67.0, 75.0, 87.0]])
        self.assertEqual(payload.confidences, [0.9, 0.8])
        self.assertEqual(payload.class_ids, [1, 3])
        self.assertEqual(model._model.engine_path, "Model/test.engine")
        self.assertEqual(model._model.task, "detect")
        self.assertEqual(len(model._model.predict_calls), 1)
        self.assertEqual(model._model.predict_calls[0]["imgsz"], 640)
        self.assertEqual(model._model.predict_calls[0]["conf"], 0.25)
        self.assertFalse(model._model.predict_calls[0]["verbose"])


if __name__ == "__main__":
    unittest.main()

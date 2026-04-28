import os
import unittest


try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None


@unittest.skipUnless(os.environ.get("RUN_YOLO_SMOKE") == "1", "set RUN_YOLO_SMOKE=1 to run engine smoke test")
@unittest.skipIf(YOLO is None, "ultralytics is not installed")
class YoloSmokeTests(unittest.TestCase):
    def test_engine_can_run_sample_image(self) -> None:
        model_path = os.path.join("Model", "yolo12n_cs2.engine")
        if not os.path.exists(model_path):
            self.skipTest(f"model file not found: {model_path}")

        model = YOLO(model_path, task="detect")
        results = model("https://ultralytics.com/images/bus.jpg")

        self.assertIsNotNone(results)


if __name__ == "__main__":
    unittest.main()

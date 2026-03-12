import unittest
from unittest.mock import patch

from src.csgo_vision_demo.config import RealtimeConfig
from src.csgo_vision_demo.realtime_engine import DetectionEngine


class _FakeWorker:
    def __init__(self, *args, **kwargs):
        self.last_error = "AttributeError: fake capture failure"
        self.width = 0
        self.height = 0

    def start(self):
        return None

    def stop(self):
        return None

    def join(self, timeout=None):
        return None


class RealtimeEngineTests(unittest.TestCase):
    @patch("src.csgo_vision_demo.realtime_engine._CaptureWorker", _FakeWorker)
    @patch("src.csgo_vision_demo.realtime_engine.DetectionEngine._wait_for_frame", return_value=None)
    def test_start_surfaces_last_capture_error(self, _mock_wait):
        engine = DetectionEngine(RealtimeConfig())
        with self.assertRaises(RuntimeError) as ctx:
            engine.start()
        self.assertIn("Last capture error: AttributeError: fake capture failure", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

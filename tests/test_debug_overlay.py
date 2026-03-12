import unittest
from unittest.mock import patch

from src.csgo_vision_demo.config import DebugSection
from src.csgo_vision_demo.debug_overlay import DebugOverlay, RealtimeDebugState, build_debug_lines
from src.csgo_vision_demo.realtime_engine import DetectionSnapshot


class DebugOverlayTests(unittest.TestCase):
    def test_build_debug_lines_contains_expected_summary(self):
        lines = build_debug_lines(
            RealtimeDebugState(
                engine_status="running",
                fps=27.4,
                aim_active=True,
                detections=2,
                primary_summary="person 0.91 nose dx=12 dy=-8",
                action_summary="move (4.0, -2.0)",
                inference_ms=14.2,
                error=None,
            )
        )
        self.assertEqual(lines[0], "Realtime Debug")
        self.assertIn("Engine: running", lines)
        self.assertIn("FPS: 27.4", lines)
        self.assertIn("Aim: ON", lines)
        self.assertIn("Detections: 2", lines)
        self.assertIn("Infer: 14.2 ms", lines)
        self.assertIn("Target: person 0.91 nose dx=12 dy=-8", lines)
        self.assertIn("Action: move (4.0, -2.0)", lines)

    @patch("src.csgo_vision_demo.debug_overlay.cv2.waitKey")
    @patch("src.csgo_vision_demo.debug_overlay.cv2.imshow")
    def test_update_skips_when_refresh_interval_not_reached(self, mock_imshow, mock_waitkey):
        overlay = DebugOverlay(DebugSection(enabled=True, refresh_ms=200))
        overlay._available = True
        overlay._last_update_at = 100.0
        snapshot = DetectionSnapshot(status="running", frame_id=1, captured_at=0.0)
        state = RealtimeDebugState("running", 0.0, False, 0, "No target", "idle", 0.0, None)
        with patch("src.csgo_vision_demo.debug_overlay.time.perf_counter", return_value=100.05):
            updated, elapsed_ms = overlay.update(snapshot, state)
        self.assertFalse(updated)
        self.assertEqual(elapsed_ms, 0.0)
        mock_imshow.assert_not_called()
        mock_waitkey.assert_not_called()


if __name__ == "__main__":
    unittest.main()

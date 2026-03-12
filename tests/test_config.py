import unittest

from src.csgo_vision_demo.config import _build_config


class ConfigTests(unittest.TestCase):
    def test_debug_defaults_are_loaded(self):
        cfg = _build_config({})
        self.assertTrue(cfg.debug.enabled)
        self.assertEqual(cfg.debug.window_width, 360)
        self.assertEqual(cfg.debug.window_height, 200)
        self.assertEqual(cfg.debug.top_right_margin, 24)
        self.assertEqual(cfg.debug.refresh_ms, 150)
        self.assertEqual(cfg.debug.perf_log_interval_sec, 5.0)
        self.assertTrue(cfg.debug.save_frames)
        self.assertEqual(cfg.debug.save_interval_sec, 5.0)
        self.assertEqual(cfg.debug.output_dir, "outputs/realtime_debug")
        self.assertEqual(cfg.runtime.log_interval_sec, 5.0)
        self.assertEqual(cfg.runtime.warmup_frames, 1)
        self.assertEqual(cfg.runtime.max_stale_frame_ms, 500.0)
        self.assertEqual(cfg.runtime.capture_sleep_ms, 1.0)
        self.assertEqual(cfg.aim.target_strategy, "nearest_head_to_center")
        self.assertEqual(cfg.aim.min_keypoint_confidence, 0.35)
        self.assertEqual(cfg.hotkeys.mode, "hold")

    def test_debug_config_overrides_are_loaded(self):
        cfg = _build_config(
            {
                "debug": {
                    "enabled": False,
                    "window_width": 420,
                    "window_height": 260,
                    "top_right_margin": 12,
                    "refresh_ms": 220,
                    "perf_log_interval_sec": 3.5,
                    "save_frames": False,
                    "save_interval_sec": 2.0,
                    "output_dir": "tmp/debug",
                },
                "runtime": {
                    "log_interval_sec": 4.0,
                    "warmup_frames": 2,
                    "max_stale_frame_ms": 250.0,
                    "capture_sleep_ms": 2.5,
                },
                "aim": {
                    "target_strategy": "nearest_head_to_center",
                    "min_keypoint_confidence": 0.5,
                },
                "hotkeys": {
                    "mode": "toggle",
                },
            }
        )
        self.assertFalse(cfg.debug.enabled)
        self.assertEqual(cfg.debug.window_width, 420)
        self.assertEqual(cfg.debug.window_height, 260)
        self.assertEqual(cfg.debug.top_right_margin, 12)
        self.assertEqual(cfg.debug.refresh_ms, 220)
        self.assertEqual(cfg.debug.perf_log_interval_sec, 3.5)
        self.assertFalse(cfg.debug.save_frames)
        self.assertEqual(cfg.debug.save_interval_sec, 2.0)
        self.assertEqual(cfg.debug.output_dir, "tmp/debug")
        self.assertEqual(cfg.runtime.log_interval_sec, 4.0)
        self.assertEqual(cfg.runtime.warmup_frames, 2)
        self.assertEqual(cfg.runtime.max_stale_frame_ms, 250.0)
        self.assertEqual(cfg.runtime.capture_sleep_ms, 2.5)
        self.assertEqual(cfg.aim.target_strategy, "nearest_head_to_center")
        self.assertEqual(cfg.aim.min_keypoint_confidence, 0.5)
        self.assertEqual(cfg.hotkeys.mode, "toggle")


if __name__ == "__main__":
    unittest.main()

import os
import sys
import types
import unittest
from types import SimpleNamespace

import numpy as np


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


_moves: list[tuple[int, int, str]] = []
_PIXEL_SCALE = np.float32(1.0 / 255.0)


def _record_move(dx: int, dy: int, method: str = "mouse_event") -> None:
    _moves.append((dx, dy, method))


def _reference_preprocess(image: np.ndarray, model_input_size: int) -> np.ndarray:
    height, width = image.shape[:2]
    output = np.zeros((1, 3, model_input_size, model_input_size), dtype=np.float32)

    if image.shape[2] == 4:
        rgb = image[:, :, 2::-1]
    else:
        rgb = image

    output[0, :, :height, :width] = np.moveaxis(rgb.astype(np.float32), -1, 0) * _PIXEL_SCALE
    return output


fake_win_utils = types.ModuleType("win_utils")
fake_win_utils.is_key_pressed = lambda _key: False
fake_win_utils.send_mouse_move = _record_move
fake_win_utils.send_mouse_click = lambda method="mouse_event": None
sys.modules.setdefault("win_utils", fake_win_utils)

fake_win32api = types.ModuleType("win32api")
fake_win32api.GetCursorPos = lambda: (960, 540)
sys.modules.setdefault("win32api", fake_win32api)

fake_mss = types.ModuleType("mss")
fake_mss.exception = types.SimpleNamespace(ScreenShotError=RuntimeError)
fake_mss.mss = lambda: None
sys.modules.setdefault("mss", fake_mss)

from core.ai_loop import _calculate_detection_region
from core.config import apply_model_constraints, bump_runtime_refresh_token, migrate_config_data
from core.control_loop import ControlLoopState, _select_target, run_control_step
from core.detection_state import DetectionFrame, DetectionPayload, LatestDetectionState
from core.inference import PIDController, preprocess_image
from core.model_registry import resolve_model_spec_from_path
from core.smart_tracker import SmartTracker


class AimStabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        _moves.clear()

    def _make_config(self, **overrides):
        defaults = {
            "sticky_target_enabled": True,
            "lock_retain_radius_px": 48.0,
            "lock_retain_time_s": 0.12,
            "target_point_smoothing_alpha": 1.0,
            "tracker_enabled": True,
            "tracker_show_prediction": True,
            "prediction_lead_time_s": 0.018,
            "velocity_ema_alpha": 0.45,
            "velocity_deadzone_px_per_s": 10.0,
            "screen_motion_compensation_enabled": True,
            "screen_motion_compensation_ratio": 1.0,
            "prediction_max_distance_px": 20.0,
            "aim_position_deadzone_px": 3.0,
            "bezier_curve_enabled": False,
            "bezier_curve_strength": 0.35,
            "tracker_current_x": 0.0,
            "tracker_current_y": 0.0,
            "tracker_predicted_x": 0.0,
            "tracker_predicted_y": 0.0,
            "tracker_has_prediction": False,
            "mouse_move_method": "mouse_event",
            "detect_interval": 0.02,
            "control_stale_hold_ms": 12.0,
            "control_stale_decay_ms": 24.0,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _make_frame(
        self,
        sequence: int,
        crosshair_x: int,
        crosshair_y: int,
        aiming_active: bool,
        payload: DetectionPayload,
        captured_perf: float = 0.0,
    ) -> DetectionFrame:
        return DetectionFrame(
            sequence=sequence,
            captured_perf=captured_perf,
            crosshair_x=crosshair_x,
            crosshair_y=crosshair_y,
            aiming_active=aiming_active,
            payload=payload,
        )

    def test_pid_is_time_aware_for_integral_term(self) -> None:
        slow = PIDController(0.0, 2.0, 0.0)
        fast = PIDController(0.0, 2.0, 0.0)

        slow_output = 0.0
        fast_output = 0.0

        for _ in range(10):
            slow_output = slow.update(5.0, 0.1)

        for _ in range(20):
            fast_output = fast.update(5.0, 0.05)

        self.assertAlmostEqual(slow_output, fast_output, places=5)

    def test_migrate_config_maps_legacy_keys_and_pid_units(self) -> None:
        migrated = migrate_config_data(
            {
                "detect_interval": 0.02,
                "single_target_mode": False,
                "tracker_prediction_time": 0.04,
                "tracker_smoothing_factor": 0.66,
                "tracker_stop_threshold": 12.0,
                "pid_ki_x": 0.5,
                "pid_kd_x": 0.25,
            }
        )

        self.assertFalse(migrated["sticky_target_enabled"])
        self.assertAlmostEqual(migrated["prediction_lead_time_s"], 0.04)
        self.assertAlmostEqual(migrated["velocity_ema_alpha"], 0.34)
        self.assertAlmostEqual(migrated["velocity_deadzone_px_per_s"], 12.0)
        self.assertAlmostEqual(migrated["pid_ki_x"], 25.0)
        self.assertAlmostEqual(migrated["pid_kd_x"], 0.005)
        self.assertEqual(migrated["controller_version"], 2)

    def test_apply_model_constraints_preserves_dynamic_tracking_defaults(self) -> None:
        from core.config import Config

        config = Config()

        self.assertTrue(config.tracker_enabled)
        self.assertTrue(config.screen_motion_compensation_enabled)
        self.assertAlmostEqual(config.screen_motion_compensation_ratio, 1.0)
        self.assertAlmostEqual(config.prediction_lead_time_s, 0.05)
        self.assertAlmostEqual(config.velocity_ema_alpha, 0.45)
        self.assertAlmostEqual(config.prediction_max_distance_px, 40.0)
        self.assertAlmostEqual(config.control_stale_hold_ms, 20.0)
        self.assertAlmostEqual(config.control_stale_decay_ms, 40.0)

    def test_runtime_refresh_token_helper_increments_monotonically(self) -> None:
        config = SimpleNamespace(runtime_refresh_token=0)

        self.assertEqual(bump_runtime_refresh_token(config), 1)
        self.assertEqual(bump_runtime_refresh_token(config), 2)

    def test_capture_backend_migration_maps_mss_to_dxcam(self) -> None:
        migrated = migrate_config_data({"capture_backend": "mss"})

        config = SimpleNamespace(capture_backend=migrated["capture_backend"])
        from core.config import _validate_capture_backend

        _validate_capture_backend(config)
        self.assertEqual(config.capture_backend, "dxcam")

    def test_latest_detection_state_only_exposes_newest_frame(self) -> None:
        state = LatestDetectionState()
        first = self._make_frame(1, 100, 100, True, DetectionPayload([], [], []))
        second = self._make_frame(2, 200, 200, False, DetectionPayload([[1.0, 2.0, 3.0, 4.0]], [0.9], [0]))

        state.publish(first)
        state.publish(second)

        snapshot = state.snapshot()
        self.assertIs(snapshot, second)
        self.assertEqual(snapshot.sequence, 2)
        self.assertEqual(snapshot.crosshair_x, 200)

    def test_detection_payload_normalizes_inputs_to_read_only_arrays(self) -> None:
        payload = DetectionPayload([[1, 2, 3, 4]], [0.5], [1])

        self.assertEqual(payload.boxes.shape, (1, 4))
        self.assertEqual(payload.confidences.dtype, np.float32)
        self.assertEqual(payload.class_ids.dtype, np.int32)
        self.assertFalse(payload.boxes.flags.writeable)

    def test_sticky_lock_prefers_existing_target_over_nearer_switch(self) -> None:
        config = self._make_config()
        state = ControlLoopState(
            locked_box=(100.0, 100.0, 120.0, 120.0),
            lock_last_seen_time=10.0,
            smoothed_target_x=110.0,
            smoothed_target_y=110.0,
            target_locked=True,
            lock_match_frames=2,
        )
        payload = DetectionPayload(
            boxes=[
                [92.0, 92.0, 108.0, 108.0],
                [101.0, 101.0, 121.0, 121.0],
            ],
            confidences=[0.9, 0.95],
            class_ids=[0, 0],
        )

        selected_box, _, _, target_changed, hold_lock = _select_target(
            config,
            payload,
            100,
            100,
            state,
            current_time=10.02,
        )

        self.assertEqual(selected_box, (101.0, 101.0, 121.0, 121.0))
        self.assertFalse(target_changed)
        self.assertFalse(hold_lock)

    def test_lock_retention_holds_without_switching_on_temporary_miss(self) -> None:
        config = self._make_config()
        state = ControlLoopState(
            locked_box=(100.0, 100.0, 120.0, 120.0),
            lock_last_seen_time=10.0,
            smoothed_target_x=110.0,
            smoothed_target_y=110.0,
            target_locked=True,
            lock_match_frames=4,
        )
        payload = DetectionPayload(
            boxes=[[250.0, 250.0, 280.0, 280.0]],
            confidences=[0.9],
            class_ids=[0],
        )

        selected_box, target_x, target_y, target_changed, hold_lock = _select_target(
            config,
            payload,
            100,
            100,
            state,
            current_time=10.05,
        )

        self.assertIsNone(selected_box)
        self.assertIsNone(target_x)
        self.assertIsNone(target_y)
        self.assertFalse(target_changed)
        self.assertTrue(hold_lock)

    def test_control_step_respects_position_deadzone(self) -> None:
        config = self._make_config()
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.26, 0.0, 0.0)
        pid_y = PIDController(0.26, 0.0, 0.0)
        payload = DetectionPayload(
            boxes=[[100.0, 100.0, 102.0, 102.0]],
            confidences=[0.9],
            class_ids=[0],
        )
        frame = self._make_frame(1, 103, 103, True, payload)

        result = run_control_step(
            config,
            state,
            pid_x,
            pid_y,
            frame,
            current_perf=5.0,
            current_time=5.0,
            tick_dt=0.02,
        )

        self.assertEqual(result.phase, "fresh")
        self.assertEqual(_moves, [])

    def test_control_step_does_not_reprocess_same_sequence(self) -> None:
        config = self._make_config(aim_position_deadzone_px=0.0)
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.2, 0.0, 0.0)
        pid_y = PIDController(0.2, 0.0, 0.0)
        payload = DetectionPayload(
            boxes=[[110.0, 100.0, 130.0, 120.0]],
            confidences=[0.9],
            class_ids=[0],
        )
        frame = self._make_frame(7, 100, 100, True, payload)

        first = run_control_step(config, state, pid_x, pid_y, frame, 1.0, 1.0, 0.02)
        first_match_frames = state.lock_match_frames
        first_update_perf = state.last_target_update_perf

        second = run_control_step(config, state, pid_x, pid_y, frame, 1.01, 1.01, 0.01)

        self.assertEqual(first.phase, "fresh")
        self.assertEqual(second.phase, "hold")
        self.assertEqual(state.lock_match_frames, first_match_frames)
        self.assertEqual(state.last_target_update_perf, first_update_perf)

    def test_control_step_transitions_from_hold_to_decay_to_idle(self) -> None:
        config = self._make_config(aim_position_deadzone_px=0.0)
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.3, 0.0, 0.0)
        pid_y = PIDController(0.3, 0.0, 0.0)
        payload = DetectionPayload(
            boxes=[[110.0, 100.0, 130.0, 120.0]],
            confidences=[0.9],
            class_ids=[0],
        )
        frame = self._make_frame(1, 100, 100, True, payload)

        fresh = run_control_step(config, state, pid_x, pid_y, frame, 1.0, 1.0, 0.02)
        hold = run_control_step(config, state, pid_x, pid_y, frame, 1.01, 1.01, 0.01)
        decay = run_control_step(config, state, pid_x, pid_y, frame, 1.02, 1.02, 0.01)
        idle = run_control_step(config, state, pid_x, pid_y, frame, 1.04, 1.04, 0.02)

        self.assertEqual(fresh.phase, "fresh")
        self.assertEqual(hold.phase, "hold")
        self.assertEqual(decay.phase, "decay")
        self.assertEqual(idle.phase, "idle")
        self.assertFalse(state.target_locked)

    def test_control_step_keeps_hold_phase_on_temporary_miss_frame(self) -> None:
        config = self._make_config(aim_position_deadzone_px=0.0)
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.3, 0.0, 0.0)
        pid_y = PIDController(0.3, 0.0, 0.0)
        target_payload = DetectionPayload(
            boxes=[[110.0, 100.0, 130.0, 120.0]],
            confidences=[0.9],
            class_ids=[0],
        )
        miss_payload = DetectionPayload([], [], [])

        fresh_frame = self._make_frame(1, 100, 100, True, target_payload)
        miss_frame = self._make_frame(2, 100, 100, True, miss_payload)

        run_control_step(config, state, pid_x, pid_y, fresh_frame, 1.0, 1.0, 0.02)
        miss = run_control_step(config, state, pid_x, pid_y, miss_frame, 1.01, 1.01, 0.01)

        self.assertEqual(miss.phase, "hold")
        self.assertTrue(state.target_locked)

    def test_control_step_resets_immediately_when_aiming_disabled(self) -> None:
        config = self._make_config(aim_position_deadzone_px=0.0)
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.3, 0.0, 0.0)
        pid_y = PIDController(0.3, 0.0, 0.0)
        payload = DetectionPayload(
            boxes=[[110.0, 100.0, 130.0, 120.0]],
            confidences=[0.9],
            class_ids=[0],
        )

        active_frame = self._make_frame(1, 100, 100, True, payload)
        inactive_frame = self._make_frame(2, 100, 100, False, payload)

        run_control_step(config, state, pid_x, pid_y, active_frame, 1.0, 1.0, 0.02)
        result = run_control_step(config, state, pid_x, pid_y, inactive_frame, 1.01, 1.01, 0.01)

        self.assertEqual(result.phase, "idle")
        self.assertFalse(state.target_locked)
        self.assertIsNone(state.control_target_x)

    def test_apply_model_constraints_locks_detect_range_to_model_input(self) -> None:
        config = SimpleNamespace(
            model_id="",
            model_path="Model/CS2.onnx",
            model_input_size=0,
            active_target_class="invalid",
            detect_range_size=560,
            fov_size=900,
            width=1920,
            height=1080,
        )

        apply_model_constraints(config)

        self.assertEqual(config.model_input_size, 640)
        self.assertEqual(config.detect_range_size, 640)
        self.assertEqual(config.fov_size, 640)
        self.assertEqual(config.active_target_class, "c")
        self.assertEqual(config.model_id, "yolo12n_cs2")
        self.assertEqual(config.model_path, "Model/yolo12n_cs2.engine")

    def test_model_registry_resolves_engine_and_legacy_onnx_paths(self) -> None:
        legacy_spec = resolve_model_spec_from_path("Model/CS2.onnx")
        engine_spec = resolve_model_spec_from_path("Model/yolo12n_cs2.engine")

        self.assertIsNotNone(legacy_spec)
        self.assertIsNotNone(engine_spec)
        self.assertEqual(legacy_spec.model_id, "yolo12n_cs2")
        self.assertEqual(engine_spec.model_id, "yolo12n_cs2")

    def test_detection_region_stays_fixed_size_near_screen_edges(self) -> None:
        config = SimpleNamespace(
            detect_range_size=640,
            fov_size=320,
            width=1920,
            height=1080,
        )

        top_left = _calculate_detection_region(config, 10, 10)
        bottom_right = _calculate_detection_region(config, 1910, 1070)

        self.assertEqual(top_left, {"left": 0, "top": 0, "width": 640, "height": 640})
        self.assertEqual(bottom_right, {"left": 1280, "top": 440, "width": 640, "height": 640})

    def test_preprocess_image_reuses_buffer_without_resize(self) -> None:
        image = np.random.randint(0, 256, (640, 640, 3), dtype=np.uint8)
        buffer = np.full((1, 3, 640, 640), -1.0, dtype=np.float32)

        result = preprocess_image(image, 640, buffer)
        expected = _reference_preprocess(image, 640)

        self.assertIs(result, buffer)
        self.assertEqual(result.shape, (1, 3, 640, 640))
        np.testing.assert_allclose(result, expected, rtol=0.0, atol=1e-6)

    def test_preprocess_image_pads_smaller_frames_instead_of_resizing(self) -> None:
        image = np.full((320, 320, 3), 128, dtype=np.uint8)
        result = preprocess_image(image, 640)
        expected = _reference_preprocess(image, 640)

        self.assertEqual(result.shape, (1, 3, 640, 640))
        np.testing.assert_allclose(result, expected, rtol=0.0, atol=1e-6)

    def test_preprocess_image_four_channel_fallback_matches_reference(self) -> None:
        image = np.random.randint(0, 256, (320, 320, 4), dtype=np.uint8)
        result = preprocess_image(image, 640)
        expected = _reference_preprocess(image, 640)

        self.assertEqual(result.shape, (1, 3, 640, 640))
        np.testing.assert_allclose(result, expected, rtol=0.0, atol=1e-6)

    def test_tracker_resets_on_reverse_and_clamps_prediction_distance(self) -> None:
        tracker = SmartTracker(velocity_ema_alpha=0.35, velocity_deadzone_px_per_s=0.0)
        tracker.update(0.0, 0.0, 0.1, 96.0)
        tracker.update(10.0, 0.0, 0.1, 96.0, motion_dx=10.0, motion_dy=0.0)
        forward_prediction = tracker.get_predicted_position(0.1, 32.0)

        tracker.update(5.0, 0.0, 0.1, 96.0, motion_dx=-5.0, motion_dy=0.0)
        reverse_prediction = tracker.get_predicted_position(1.0, 3.0)

        self.assertGreater(forward_prediction[0], 10.0)
        self.assertLess(tracker.vx, 0.0)
        self.assertAlmostEqual(reverse_prediction[0], 2.0, places=5)

    def test_tracker_uses_relative_motion_override(self) -> None:
        tracker = SmartTracker(velocity_ema_alpha=1.0, velocity_deadzone_px_per_s=0.0)
        tracker.update(120.0, 100.0, 0.1, 96.0)
        tracker.update(110.0, 100.0, 0.1, 96.0, motion_dx=0.0, motion_dy=0.0)
        predicted_x, predicted_y = tracker.get_predicted_position(0.05, 20.0)

        self.assertEqual((predicted_x, predicted_y), (110.0, 100.0))
        self.assertEqual((tracker.vx, tracker.vy), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()

import os
import sys
import types
import unittest
from types import SimpleNamespace


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


_moves: list[tuple[int, int, str]] = []


def _record_move(dx: int, dy: int, method: str = "mouse_event") -> None:
    _moves.append((dx, dy, method))


fake_win_utils = types.ModuleType("win_utils")
fake_win_utils.is_key_pressed = lambda _key: False
fake_win_utils.send_mouse_move = _record_move
fake_win_utils.send_mouse_click = lambda method="mouse_event": None
sys.modules["win_utils"] = fake_win_utils


import core.control_loop as control_loop_module
from core.control_loop import (
    ControlLoopState,
    _get_target_smoothing_alpha,
    _resolve_control_tick_interval,
    run_control_step,
)
from core.detection_state import DetectionFrame, DetectionPayload
from core.inference import PIDController


control_loop_module.send_mouse_move = _record_move


class ControlLoopCompensationTests(unittest.TestCase):
    def setUp(self) -> None:
        _moves.clear()

    def _make_config(self, **overrides):
        defaults = {
            "sticky_target_enabled": True,
            "lock_retain_radius_px": 48.0,
            "lock_retain_time_s": 0.12,
            "target_point_smoothing_alpha": 1.0,
            "tracker_enabled": False,
            "tracker_show_prediction": True,
            "prediction_lead_time_s": 0.025,
            "velocity_ema_alpha": 0.35,
            "velocity_deadzone_px_per_s": 10.0,
            "prediction_max_distance_px": 32.0,
            "aim_position_deadzone_px": 0.0,
            "bezier_curve_enabled": False,
            "bezier_curve_strength": 0.35,
            "tracker_current_x": 0.0,
            "tracker_current_y": 0.0,
            "tracker_predicted_x": 0.0,
            "tracker_predicted_y": 0.0,
            "tracker_has_prediction": False,
            "mouse_move_method": "mouse_event",
            "detect_interval": 0.02,
            "control_stale_hold_ms": 40.0,
            "control_stale_decay_ms": 60.0,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _make_frame(
        self,
        sequence: int,
        crosshair_x: int,
        crosshair_y: int,
        payload: DetectionPayload,
    ) -> DetectionFrame:
        return DetectionFrame(
            sequence=sequence,
            captured_perf=0.0,
            crosshair_x=crosshair_x,
            crosshair_y=crosshair_y,
            aiming_active=True,
            payload=payload,
        )

    def test_repeated_ticks_on_same_detection_frame_do_not_reapply_full_error(self) -> None:
        config = self._make_config()
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.45, 0.0, 0.0)
        pid_y = PIDController(0.45, 0.0, 0.0)
        payload = DetectionPayload(
            boxes=[[110.0, 90.0, 130.0, 110.0]],
            confidences=[0.9],
            class_ids=[0],
        )
        frame = self._make_frame(7, 100, 100, payload)

        run_control_step(config, state, pid_x, pid_y, frame, 1.0, 1.0, 0.02)
        run_control_step(config, state, pid_x, pid_y, frame, 1.002, 1.002, 0.002)
        run_control_step(config, state, pid_x, pid_y, frame, 1.004, 1.004, 0.002)
        run_control_step(config, state, pid_x, pid_y, frame, 1.006, 1.006, 0.002)

        x_moves = [dx for dx, _, _ in _moves]
        self.assertEqual(x_moves, [16, 2, 1, 1])
        self.assertLessEqual(sum(x_moves), 20)

    def test_single_tick_output_is_clamped_to_current_error(self) -> None:
        config = self._make_config()
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(1.0, 0.0, 0.0)
        pid_y = PIDController(1.0, 0.0, 0.0)
        payload = DetectionPayload(
            boxes=[[110.0, 90.0, 130.0, 110.0]],
            confidences=[0.9],
            class_ids=[0],
        )
        frame = self._make_frame(7, 100, 100, payload)

        run_control_step(config, state, pid_x, pid_y, frame, 1.0, 1.0, 0.02)

        self.assertEqual(_moves, [(24, 0, "mouse_event")])

    def test_control_tick_interval_follows_detection_rate_under_configured_ceiling(self) -> None:
        config = self._make_config(control_loop_hz=500.0, detect_interval=0.01)
        payload = DetectionPayload([], [], [])
        frame = self._make_frame(3, 100, 100, payload)
        state = ControlLoopState(target_locked=True, detection_interval_ema_s=0.01)

        fast_interval = _resolve_control_tick_interval(config, state, frame)
        self.assertAlmostEqual(fast_interval, 1.0 / 200.0, places=4)

        state.detection_interval_ema_s = 0.04
        slow_interval = _resolve_control_tick_interval(config, state, frame)
        self.assertAlmostEqual(slow_interval, 1.0 / 60.0, places=4)

    def test_acquire_stage_pushes_harder_than_track_stage(self) -> None:
        config = self._make_config(target_point_smoothing_alpha=0.35)
        payload = DetectionPayload(
            boxes=[[110.0, 90.0, 130.0, 110.0]],
            confidences=[0.9],
            class_ids=[0],
        )
        frame = self._make_frame(7, 100, 100, payload)

        acquire_state = ControlLoopState(cached_mouse_move_method="mouse_event")
        acquire_pid_x = PIDController(0.45, 0.0, 0.0)
        acquire_pid_y = PIDController(0.45, 0.0, 0.0)
        run_control_step(config, acquire_state, acquire_pid_x, acquire_pid_y, frame, 1.0, 1.0, 0.02)
        acquire_move = _moves[-1]

        _moves.clear()
        track_state = ControlLoopState(
            cached_mouse_move_method="mouse_event",
            target_locked=True,
            locked_box=(110.0, 90.0, 130.0, 110.0),
            lock_acquired_time=0.7,
            lock_last_seen_time=0.99,
            lock_match_frames=5,
            smoothed_target_x=120.0,
            smoothed_target_y=100.0,
        )
        track_pid_x = PIDController(0.45, 0.0, 0.0)
        track_pid_y = PIDController(0.45, 0.0, 0.0)
        run_control_step(config, track_state, track_pid_x, track_pid_y, frame, 1.0, 1.0, 0.02)
        track_move = _moves[-1]

        self.assertEqual(acquire_state.control_stage, "acquire")
        self.assertEqual(track_state.control_stage, "track")
        self.assertGreater(abs(acquire_move[0]), abs(track_move[0]))

    def test_settle_stage_keeps_advancing_small_error(self) -> None:
        config = self._make_config(target_point_smoothing_alpha=0.35)
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.1, 0.0, 0.0)
        pid_y = PIDController(0.1, 0.0, 0.0)
        payload = DetectionPayload(
            boxes=[[101.0, 100.0, 103.0, 102.0]],
            confidences=[0.9],
            class_ids=[0],
        )
        frame = self._make_frame(1, 100, 100, payload)

        result = run_control_step(config, state, pid_x, pid_y, frame, 2.0, 2.0, 0.02)

        self.assertEqual(result.phase, "fresh")
        self.assertEqual(state.control_stage, "settle")
        self.assertEqual(_moves[-1], (1, 1, "mouse_event"))

    def test_stage_smoothing_alpha_is_more_aggressive_on_acquire_than_track(self) -> None:
        config = self._make_config(target_point_smoothing_alpha=0.35)
        acquire_state = ControlLoopState(target_locked=True, lock_acquired_time=1.0, lock_match_frames=1)
        track_state = ControlLoopState(target_locked=True, lock_acquired_time=0.0, lock_match_frames=6)

        acquire_alpha = _get_target_smoothing_alpha(config, acquire_state, 140.0, 100.0, 100, 100, 1.02)
        track_alpha = _get_target_smoothing_alpha(config, track_state, 140.0, 100.0, 100, 100, 1.02)

        self.assertGreater(acquire_alpha, track_alpha)


if __name__ == "__main__":
    unittest.main()

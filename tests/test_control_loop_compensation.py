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
fake_win_utils.__path__ = []
fake_win_utils.is_key_pressed = lambda _key: False
fake_win_utils.send_mouse_move = _record_move
fake_win_utils.send_mouse_click = lambda method="mouse_event": None
fake_key_utils = types.ModuleType("win_utils.key_utils")
fake_key_utils.is_key_pressed = fake_win_utils.is_key_pressed
fake_win_utils.key_utils = fake_key_utils
sys.modules["win_utils"] = fake_win_utils
sys.modules["win_utils.key_utils"] = fake_key_utils


import core.control_loop as control_loop_module
from core.control_loop import (
    ControlLoopState,
    _get_target_smoothing_alpha,
    _resolve_control_tick_interval,
    _select_target,
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
            "tracker_enabled": True,
            "tracker_show_prediction": True,
            "prediction_lead_time_s": 0.018,
            "velocity_ema_alpha": 0.45,
            "velocity_deadzone_px_per_s": 10.0,
            "screen_motion_compensation_enabled": True,
            "screen_motion_compensation_ratio": 1.0,
            "prediction_max_distance_px": 20.0,
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

    def test_select_target_prefers_nearest_candidate_without_sorting_side_effects(self) -> None:
        config = self._make_config()
        state = ControlLoopState()
        payload = DetectionPayload(
            boxes=[
                [140.0, 90.0, 160.0, 110.0],
                [105.0, 95.0, 125.0, 115.0],
                [170.0, 90.0, 190.0, 110.0],
            ],
            confidences=[0.7, 0.8, 0.9],
            class_ids=[0, 0, 0],
        )

        selected_box, target_x, target_y, target_changed, hold_lock = _select_target(
            config,
            payload,
            100,
            100,
            state,
            1.0,
        )

        self.assertEqual(selected_box, (105.0, 95.0, 125.0, 115.0))
        self.assertEqual((target_x, target_y), (115.0, 105.0))
        self.assertFalse(target_changed)
        self.assertFalse(hold_lock)

    def test_select_target_uses_confidence_weighted_distance_for_new_lock(self) -> None:
        config = self._make_config()
        state = ControlLoopState()
        payload = DetectionPayload(
            boxes=[
                [100.0, 90.0, 120.0, 110.0],
                [108.0, 90.0, 128.0, 110.0],
            ],
            confidences=[0.1, 0.9],
            class_ids=[0, 0],
        )

        selected_box, target_x, target_y, target_changed, hold_lock = _select_target(
            config,
            payload,
            100,
            100,
            state,
            1.0,
        )

        self.assertEqual(selected_box, (108.0, 90.0, 128.0, 110.0))
        self.assertEqual((target_x, target_y), (118.0, 100.0))
        self.assertFalse(target_changed)
        self.assertFalse(hold_lock)

    def test_select_target_prefers_locked_match_over_nearest_candidate(self) -> None:
        config = self._make_config()
        state = ControlLoopState(
            target_locked=True,
            locked_box=(150.0, 95.0, 170.0, 115.0),
            lock_last_seen_time=0.99,
        )
        payload = DetectionPayload(
            boxes=[
                [104.0, 95.0, 124.0, 115.0],
                [152.0, 96.0, 172.0, 116.0],
            ],
            confidences=[0.8, 0.85],
            class_ids=[0, 0],
        )

        selected_box, target_x, target_y, target_changed, hold_lock = _select_target(
            config,
            payload,
            100,
            100,
            state,
            1.0,
        )

        self.assertEqual(selected_box, (152.0, 96.0, 172.0, 116.0))
        self.assertEqual((target_x, target_y), (162.0, 106.0))
        self.assertFalse(target_changed)
        self.assertFalse(hold_lock)

    def test_self_motion_is_removed_from_tracker_velocity(self) -> None:
        config = self._make_config(aim_position_deadzone_px=0.0)
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.2, 0.0, 0.0)
        pid_y = PIDController(0.2, 0.0, 0.0)

        first = self._make_frame(
            1,
            100,
            100,
            DetectionPayload(boxes=[[110.0, 90.0, 130.0, 110.0]], confidences=[0.9], class_ids=[0]),
        )
        second = self._make_frame(
            2,
            112,
            100,
            DetectionPayload(boxes=[[98.0, 90.0, 118.0, 110.0]], confidences=[0.9], class_ids=[0]),
        )

        run_control_step(config, state, pid_x, pid_y, first, 1.0, 1.0, 0.02)
        run_control_step(config, state, pid_x, pid_y, second, 1.02, 1.02, 0.02)

        self.assertIsNotNone(state.smart_tracker)
        self.assertAlmostEqual(state.smart_tracker.vx, 0.0, places=5)
        self.assertAlmostEqual(config.tracker_predicted_x, state.measured_target_x, places=5)

    def test_tracker_applies_prediction_for_moving_target(self) -> None:
        config = self._make_config(
            aim_position_deadzone_px=0.0,
            velocity_deadzone_px_per_s=0.0,
            prediction_lead_time_s=0.02,
        )
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.2, 0.0, 0.0)
        pid_y = PIDController(0.2, 0.0, 0.0)
        frames = [
            self._make_frame(
                1,
                100,
                100,
                DetectionPayload(boxes=[[110.0, 90.0, 130.0, 110.0]], confidences=[0.9], class_ids=[0]),
            ),
            self._make_frame(
                2,
                100,
                100,
                DetectionPayload(boxes=[[114.0, 90.0, 134.0, 110.0]], confidences=[0.9], class_ids=[0]),
            ),
            self._make_frame(
                3,
                100,
                100,
                DetectionPayload(boxes=[[118.0, 90.0, 138.0, 110.0]], confidences=[0.9], class_ids=[0]),
            ),
        ]

        run_control_step(config, state, pid_x, pid_y, frames[0], 1.0, 1.0, 0.02)
        run_control_step(config, state, pid_x, pid_y, frames[1], 1.02, 1.02, 0.02)
        run_control_step(config, state, pid_x, pid_y, frames[2], 1.04, 1.04, 0.02)

        self.assertTrue(state.tracker_active)
        self.assertGreater(config.tracker_predicted_x, state.measured_target_x)

    def test_hold_tick_extends_prediction_by_target_age(self) -> None:
        config = self._make_config(
            aim_position_deadzone_px=0.0,
            velocity_deadzone_px_per_s=0.0,
            prediction_lead_time_s=0.02,
        )
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.2, 0.0, 0.0)
        pid_y = PIDController(0.2, 0.0, 0.0)
        frames = [
            self._make_frame(
                1,
                100,
                100,
                DetectionPayload(boxes=[[110.0, 90.0, 130.0, 110.0]], confidences=[0.9], class_ids=[0]),
            ),
            self._make_frame(
                2,
                100,
                100,
                DetectionPayload(boxes=[[120.0, 90.0, 140.0, 110.0]], confidences=[0.9], class_ids=[0]),
            ),
            self._make_frame(
                3,
                100,
                100,
                DetectionPayload(boxes=[[130.0, 90.0, 150.0, 110.0]], confidences=[0.9], class_ids=[0]),
            ),
        ]

        run_control_step(config, state, pid_x, pid_y, frames[0], 1.0, 1.0, 0.005)
        run_control_step(config, state, pid_x, pid_y, frames[1], 1.005, 1.005, 0.005)
        run_control_step(config, state, pid_x, pid_y, frames[2], 1.01, 1.01, 0.005)
        fresh_prediction_x = state.control_target_x

        hold = run_control_step(config, state, pid_x, pid_y, frames[2], 1.03, 1.03, 0.005)

        self.assertFalse(hold.processed_new_frame)
        self.assertTrue(state.tracker_active)
        self.assertIsNotNone(fresh_prediction_x)
        self.assertGreater(state.control_target_x, fresh_prediction_x)

    def test_tracker_moves_on_prediction_when_measured_target_is_inside_deadzone(self) -> None:
        config = self._make_config(
            aim_position_deadzone_px=3.0,
            velocity_deadzone_px_per_s=0.0,
            prediction_lead_time_s=0.02,
        )
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.2, 0.0, 0.0)
        pid_y = PIDController(0.2, 0.0, 0.0)

        run_control_step(
            config,
            state,
            pid_x,
            pid_y,
            self._make_frame(
                1,
                100,
                100,
                DetectionPayload(boxes=[[83.0, 90.0, 103.0, 110.0]], confidences=[0.9], class_ids=[0]),
            ),
            1.0,
            1.0,
            0.005,
        )
        run_control_step(
            config,
            state,
            pid_x,
            pid_y,
            self._make_frame(
                2,
                100,
                100,
                DetectionPayload(boxes=[[87.0, 90.0, 107.0, 110.0]], confidences=[0.9], class_ids=[0]),
            ),
            1.005,
            1.005,
            0.005,
        )
        _moves.clear()

        run_control_step(
            config,
            state,
            pid_x,
            pid_y,
            self._make_frame(
                3,
                100,
                100,
                DetectionPayload(boxes=[[91.0, 90.0, 111.0, 110.0]], confidences=[0.9], class_ids=[0]),
            ),
            1.01,
            1.01,
            0.005,
        )

        self.assertTrue(state.tracker_active)
        self.assertLessEqual(abs(state.measured_target_x - 100), config.aim_position_deadzone_px)
        self.assertGreater(_moves[-1][0], 0)

    def test_dynamic_prediction_distance_exceeds_default_cap_for_fast_horizontal_target(self) -> None:
        config = self._make_config(
            aim_position_deadzone_px=0.0,
            velocity_deadzone_px_per_s=0.0,
            prediction_lead_time_s=0.02,
            prediction_max_distance_px=20.0,
        )
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.2, 0.0, 0.0)
        pid_y = PIDController(0.2, 0.0, 0.0)
        frames = [
            self._make_frame(
                1,
                100,
                100,
                DetectionPayload(boxes=[[110.0, 90.0, 130.0, 110.0]], confidences=[0.9], class_ids=[0]),
            ),
            self._make_frame(
                2,
                100,
                100,
                DetectionPayload(boxes=[[150.0, 90.0, 170.0, 110.0]], confidences=[0.9], class_ids=[0]),
            ),
            self._make_frame(
                3,
                100,
                100,
                DetectionPayload(boxes=[[190.0, 90.0, 210.0, 110.0]], confidences=[0.9], class_ids=[0]),
            ),
        ]

        run_control_step(config, state, pid_x, pid_y, frames[0], 1.0, 1.0, 0.005)
        run_control_step(config, state, pid_x, pid_y, frames[1], 1.005, 1.005, 0.005)
        run_control_step(config, state, pid_x, pid_y, frames[2], 1.01, 1.01, 0.005)

        prediction_delta = state.control_target_x - state.measured_target_x
        self.assertTrue(state.tracker_active)
        self.assertGreater(prediction_delta, config.prediction_max_distance_px)
        self.assertLessEqual(prediction_delta, 60.0)

    def test_combined_self_motion_and_target_motion_keeps_relative_velocity(self) -> None:
        config = self._make_config(
            aim_position_deadzone_px=0.0,
            velocity_deadzone_px_per_s=0.0,
        )
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.2, 0.0, 0.0)
        pid_y = PIDController(0.2, 0.0, 0.0)

        run_control_step(
            config,
            state,
            pid_x,
            pid_y,
            self._make_frame(
                1,
                100,
                100,
                DetectionPayload(boxes=[[110.0, 90.0, 130.0, 110.0]], confidences=[0.9], class_ids=[0]),
            ),
            1.0,
            1.0,
            0.02,
        )
        run_control_step(
            config,
            state,
            pid_x,
            pid_y,
            self._make_frame(
                2,
                106,
                100,
                DetectionPayload(boxes=[[108.0, 90.0, 128.0, 110.0]], confidences=[0.9], class_ids=[0]),
            ),
            1.02,
            1.02,
            0.02,
        )

        self.assertIsNotNone(state.smart_tracker)
        self.assertGreater(state.smart_tracker.vx, 0.0)
        self.assertLess(state.smart_tracker.vx, 300.0)


if __name__ == "__main__":
    unittest.main()

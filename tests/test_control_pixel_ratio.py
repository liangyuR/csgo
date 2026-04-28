"""Aim-pixel-ratio + acquire-stage no-overshoot regression tests."""

from __future__ import annotations

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
from core.control_loop import ControlLoopState, run_control_step
from core.detection_state import DetectionFrame, DetectionPayload
from core.inference import PIDController


control_loop_module.send_mouse_move = _record_move


def _make_config(**overrides):
    defaults = {
        "sticky_target_enabled": True,
        "lock_retain_radius_px": 48.0,
        "lock_retain_time_s": 0.12,
        "target_point_smoothing_alpha": 1.0,
        "tracker_enabled": True,
        "tracker_show_prediction": True,
        "prediction_lead_time_s": 0.024,
        "velocity_ema_alpha": 0.6,
        "velocity_deadzone_px_per_s": 10.0,
        "screen_motion_compensation_enabled": True,
        "screen_motion_compensation_ratio": 1.0,
        "prediction_max_distance_px": 80.0,
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
        "aim_pixel_ratio_x": 1.0,
        "aim_pixel_ratio_y": 1.0,
        "tracker_use_acceleration": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_frame(sequence: int, crosshair_x: int, crosshair_y: int, payload: DetectionPayload) -> DetectionFrame:
    return DetectionFrame(
        sequence=sequence,
        captured_perf=0.0,
        crosshair_x=crosshair_x,
        crosshair_y=crosshair_y,
        aiming_active=True,
        payload=payload,
    )


class AimPixelRatioTests(unittest.TestCase):
    def setUp(self) -> None:
        _moves.clear()

    def test_acquire_stage_never_overshoots_remaining_error(self) -> None:
        """Acquire stage no longer permits explicit overshoot. Even with a high
        ``Kp`` and the 1.25x acquire gain, the issued mouse delta is clamped
        to the exact remaining error (the box-center offset)."""
        config = _make_config()
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(2.0, 0.0, 0.0)
        pid_y = PIDController(2.0, 0.0, 0.0)
        payload = DetectionPayload(
            boxes=[[110.0, 90.0, 130.0, 110.0]],
            confidences=[0.9],
            class_ids=[0],
        )
        frame = _make_frame(1, 100, 100, payload)

        run_control_step(config, state, pid_x, pid_y, frame, 1.0, 1.0, 0.02)

        self.assertEqual(_moves, [(20, 0, "mouse_event")])

    def test_pixel_ratio_below_one_amplifies_mouse_output(self) -> None:
        """A 0.5 ratio means 1 mouse count -> 0.5 screen pixels. We therefore
        need 2x more mouse counts to cover the same screen-pixel error."""
        config = _make_config(aim_pixel_ratio_x=0.5, aim_pixel_ratio_y=0.5)
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.5, 0.0, 0.0)
        pid_y = PIDController(0.5, 0.0, 0.0)
        payload = DetectionPayload(
            boxes=[[110.0, 90.0, 130.0, 110.0]],
            confidences=[0.9],
            class_ids=[0],
        )
        frame = _make_frame(1, 100, 100, payload)

        run_control_step(config, state, pid_x, pid_y, frame, 1.0, 1.0, 0.02)

        # acquire output in screen px = round(0.5 * 20 * 1.25) = round(12.5)
        # = 12 (Python 3 banker's rounding). Clamped to remaining 20.
        # Mouse counts = 12 / 0.5 = 24.
        self.assertEqual(_moves, [(24, 0, "mouse_event")])
        self.assertAlmostEqual(state.applied_mouse_dx, 12.0)

    def test_pixel_ratio_above_one_attenuates_mouse_output(self) -> None:
        config = _make_config(aim_pixel_ratio_x=2.0, aim_pixel_ratio_y=2.0)
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.5, 0.0, 0.0)
        pid_y = PIDController(0.5, 0.0, 0.0)
        payload = DetectionPayload(
            boxes=[[110.0, 90.0, 130.0, 110.0]],
            confidences=[0.9],
            class_ids=[0],
        )
        frame = _make_frame(1, 100, 100, payload)

        run_control_step(config, state, pid_x, pid_y, frame, 1.0, 1.0, 0.02)

        # screen-pixel output = 12 (see above). mouse counts = 12 / 2.0 = 6.
        # applied_mouse_dx is recorded in screen pixels: 6 * 2.0 = 12.
        self.assertEqual(_moves, [(6, 0, "mouse_event")])
        self.assertAlmostEqual(state.applied_mouse_dx, 12.0)

    def test_extreme_ratio_does_not_explode_mouse_counts(self) -> None:
        """At the lower clamp (0.1) the system issues 10x more mouse counts
        than screen pixels of error. This documents the boundary behaviour
        end-to-end."""
        config = _make_config(aim_pixel_ratio_x=0.1, aim_pixel_ratio_y=0.1)
        state = ControlLoopState(cached_mouse_move_method="mouse_event")
        pid_x = PIDController(0.5, 0.0, 0.0)
        pid_y = PIDController(0.5, 0.0, 0.0)
        payload = DetectionPayload(
            boxes=[[110.0, 90.0, 130.0, 110.0]],
            confidences=[0.9],
            class_ids=[0],
        )
        frame = _make_frame(1, 100, 100, payload)

        run_control_step(config, state, pid_x, pid_y, frame, 1.0, 1.0, 0.02)

        # screen-pixel output = 12. mouse counts = 12 / 0.1 = 120.
        self.assertEqual(_moves, [(120, 0, "mouse_event")])


if __name__ == "__main__":
    unittest.main()

"""High-frequency aiming control loop."""

from __future__ import annotations

import logging
import math
import random
import time
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING

from win_utils import send_mouse_move

from .detection_state import DetectionFrame, DetectionPayload, LatestDetectionState
from .inference import PIDController
from .smart_tracker import SmartTracker

if TYPE_CHECKING:
    from .config import Config


logger = logging.getLogger(__name__)

Box = tuple[float, float, float, float]

_ACQUIRE_MATCH_FRAMES = 3
_ACQUIRE_WINDOW_S = 0.075
_ACQUIRE_GAIN = 1.75
_ACQUIRE_MIN_MOVE_PX = 3
_ACQUIRE_OVERSHOOT_RATIO = 0.18
_ACQUIRE_MAX_OVERSHOOT_PX = 6
_TRACK_MIN_ALPHA = 0.45
_ACQUIRE_MIN_ALPHA = 0.82
_SETTLE_MIN_ALPHA = 0.58
_SETTLE_DISTANCE_PX = 18.0
_SETTLE_MIN_MOVE_PX = 1
_SETTLE_MAX_MOVE_PX = 3


@dataclass
class ControlLoopState:
    last_tick_perf: float = 0.0
    last_pid_refresh_time: float = 0.0
    last_method_check_time: float = 0.0
    pid_check_interval: float = 1.0
    method_check_interval: float = 2.0
    cached_mouse_move_method: str = "mouse_event"
    bezier_curve_scalar: float = 0.0
    target_locked: bool = False
    smart_tracker: SmartTracker | None = None
    locked_box: Box | None = None
    lock_last_seen_time: float = 0.0
    lock_acquired_time: float = 0.0
    lock_match_frames: int = 0
    smoothed_target_x: float | None = None
    smoothed_target_y: float | None = None
    last_processed_sequence: int = -1
    last_detection_update_perf: float = 0.0
    last_target_update_perf: float = 0.0
    detection_interval_ema_s: float = 0.0
    measured_target_x: float | None = None
    measured_target_y: float | None = None
    control_target_x: float | None = None
    control_target_y: float | None = None
    applied_mouse_dx: float = 0.0
    applied_mouse_dy: float = 0.0
    control_stage: str = "idle"
    tracker_active: bool = False
    latency_last_report_time: float = 0.0
    latency_ema_tick_ms: float = 0.0
    latency_ema_hz: float = 0.0
    latency_ema_target_age_ms: float = 0.0
    latency_phase: str = "idle"


@dataclass(frozen=True)
class ControlStepResult:
    phase: str
    target_age_ms: float
    processed_new_frame: bool


def _box_to_tuple(box: list[float] | tuple[float, float, float, float]) -> Box:
    x1, y1, x2, y2 = box
    return float(x1), float(y1), float(x2), float(y2)


def _box_center(box: Box) -> tuple[float, float]:
    return (box[0] + box[2]) * 0.5, (box[1] + box[3]) * 0.5


def _distance_sq(x1: float, y1: float, x2: float, y2: float) -> float:
    return ((x1 - x2) ** 2) + ((y1 - y2) ** 2)


def _box_iou(box_a: Box, box_b: Box) -> float:
    xx1 = max(box_a[0], box_b[0])
    yy1 = max(box_a[1], box_b[1])
    xx2 = min(box_a[2], box_b[2])
    yy2 = min(box_a[3], box_b[3])

    w = max(0.0, xx2 - xx1)
    h = max(0.0, yy2 - yy1)
    intersection = w * h
    if intersection <= 0.0:
        return 0.0

    area_a = max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1])
    area_b = max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1])
    union = area_a + area_b - intersection
    if union <= 0.0:
        return 0.0
    return intersection / union


def _boxes_match(box_a: Box | None, box_b: Box | None, lock_retain_radius_px: float) -> bool:
    if box_a is None or box_b is None:
        return False

    if _box_iou(box_a, box_b) >= 0.2:
        return True

    ax, ay = _box_center(box_a)
    bx, by = _box_center(box_b)
    return _distance_sq(ax, ay, bx, by) <= (lock_retain_radius_px ** 2)


def _reset_tracker_overlay(config: Config) -> None:
    config.tracker_current_x = 0.0
    config.tracker_current_y = 0.0
    config.tracker_predicted_x = 0.0
    config.tracker_predicted_y = 0.0
    config.tracker_has_prediction = False


def _remaining_error_after_applied_move(raw_error: float, applied_delta: float) -> float:
    remaining_error = raw_error - applied_delta
    if (
        raw_error != 0.0
        and remaining_error != 0.0
        and math.copysign(1.0, raw_error) != math.copysign(1.0, remaining_error)
    ):
        return 0.0
    return remaining_error


def _clamp_move_to_error(move: int, remaining_error: float) -> int:
    if move == 0 or remaining_error == 0.0:
        return 0

    max_move = abs(int(round(remaining_error)))
    if max_move == 0:
        return 0

    return int(math.copysign(min(abs(move), max_move), move))


def _clamp_move_to_stage_limit(move: int, remaining_error: float, stage: str) -> int:
    if move == 0 or remaining_error == 0.0:
        return 0

    remaining_abs = abs(remaining_error)
    if stage == "acquire":
        overshoot = min(
            _ACQUIRE_MAX_OVERSHOOT_PX,
            max(1, int(math.ceil(remaining_abs * _ACQUIRE_OVERSHOOT_RATIO))),
        )
        max_move = max(1, int(math.ceil(remaining_abs + overshoot)))
        return int(math.copysign(min(abs(move), max_move), move))

    return _clamp_move_to_error(move, remaining_error)


def _move_toward_error(error: float, min_pixels: int, max_pixels: int | None = None) -> int:
    if error == 0.0 or min_pixels <= 0:
        return 0

    limit = max(min_pixels, 1)
    if max_pixels is not None:
        limit = min(limit, max_pixels)
    return int(math.copysign(limit, error))


def _determine_control_stage(
    state: ControlLoopState,
    final_distance: float,
    current_time: float,
) -> str:
    if not state.target_locked:
        return "idle"
    if final_distance <= _SETTLE_DISTANCE_PX:
        return "settle"
    if (
        state.lock_match_frames <= _ACQUIRE_MATCH_FRAMES
        or (current_time - state.lock_acquired_time) <= _ACQUIRE_WINDOW_S
    ):
        return "acquire"
    return "track"


def _get_target_smoothing_alpha(
    config: Config,
    state: ControlLoopState,
    target_x: float,
    target_y: float,
    crosshair_x: int,
    crosshair_y: int,
    current_time: float,
) -> float:
    base_alpha = min(max(float(getattr(config, "target_point_smoothing_alpha", 0.35)), 0.0), 1.0)
    distance = math.hypot(target_x - crosshair_x, target_y - crosshair_y)
    stage = _determine_control_stage(state, distance, current_time)
    if stage == "acquire":
        return max(base_alpha, _ACQUIRE_MIN_ALPHA)
    if stage == "settle":
        return max(base_alpha, _SETTLE_MIN_ALPHA)
    return max(base_alpha, _TRACK_MIN_ALPHA)


def _resolve_control_tick_interval(
    config: Config,
    state: ControlLoopState,
    frame: DetectionFrame | None,
) -> float:
    configured_hz = max(float(getattr(config, "control_loop_hz", 500.0) or 500.0), 1.0)
    detection_dt = state.detection_interval_ema_s
    if detection_dt <= 0.0:
        detection_dt = max(float(getattr(config, "detect_interval", 0.02) or 0.02), 0.001)

    detection_hz = 1.0 / max(detection_dt, 1e-3)
    active_hz = min(configured_hz, max(60.0, detection_hz * 2.0))
    standby_hz = min(configured_hz, max(60.0, detection_hz))
    idle_hz = min(configured_hz, 60.0)

    if frame is None or not frame.aiming_active:
        return 1.0 / idle_hz

    if state.target_locked or frame.sequence != state.last_processed_sequence:
        return 1.0 / active_hz

    return 1.0 / standby_hz


def _clear_lock_state(state: ControlLoopState) -> None:
    state.target_locked = False
    state.locked_box = None
    state.lock_last_seen_time = 0.0
    state.lock_acquired_time = 0.0
    state.lock_match_frames = 0
    state.smoothed_target_x = None
    state.smoothed_target_y = None
    state.last_target_update_perf = 0.0
    state.measured_target_x = None
    state.measured_target_y = None
    state.control_target_x = None
    state.control_target_y = None
    state.applied_mouse_dx = 0.0
    state.applied_mouse_dy = 0.0
    state.control_stage = "idle"
    state.tracker_active = False


def _reset_control_state(
    config: Config,
    state: ControlLoopState,
    pid_x: PIDController,
    pid_y: PIDController,
    clear_lock: bool = False,
) -> None:
    pid_x.reset()
    pid_y.reset()
    _reset_tracker_overlay(config)
    if state.smart_tracker is not None:
        state.smart_tracker.reset()
    if clear_lock:
        _clear_lock_state(state)


def _build_candidates(
    payload: DetectionPayload,
    crosshair_x: int,
    crosshair_y: int,
) -> list[tuple[float, float, float, Box]]:
    candidates: list[tuple[float, float, float, Box]] = []
    for box in payload.boxes:
        box_tuple = _box_to_tuple(box)
        center_x, center_y = _box_center(box_tuple)
        candidates.append(
            (
                _distance_sq(center_x, center_y, crosshair_x, crosshair_y),
                center_x,
                center_y,
                box_tuple,
            )
        )

    candidates.sort(key=lambda item: item[0])
    return candidates


def _match_locked_candidate(
    candidates: list[tuple[float, float, float, Box]],
    locked_box: Box,
    lock_retain_radius_px: float,
) -> tuple[float, float, float, Box] | None:
    locked_cx, locked_cy = _box_center(locked_box)
    best_candidate: tuple[float, float, float, Box] | None = None
    best_sort_key: tuple[float, float, float] | None = None

    for distance_sq, center_x, center_y, box in candidates:
        iou = _box_iou(box, locked_box)
        center_distance_sq = _distance_sq(center_x, center_y, locked_cx, locked_cy)
        if iou < 0.2 and center_distance_sq > (lock_retain_radius_px ** 2):
            continue

        sort_key = (-iou, center_distance_sq, distance_sq)
        if best_sort_key is None or sort_key < best_sort_key:
            best_sort_key = sort_key
            best_candidate = (distance_sq, center_x, center_y, box)

    return best_candidate


def _select_target(
    config: Config,
    payload: DetectionPayload,
    crosshair_x: int,
    crosshair_y: int,
    state: ControlLoopState,
    current_time: float,
) -> tuple[Box | None, float | None, float | None, bool, bool]:
    candidates = _build_candidates(payload, crosshair_x, crosshair_y)
    sticky_enabled = bool(getattr(config, "sticky_target_enabled", True))
    lock_retain_radius_px = float(getattr(config, "lock_retain_radius_px", 48.0))
    lock_retain_time_s = float(getattr(config, "lock_retain_time_s", 0.12))

    previous_box = state.locked_box
    selected: tuple[float, float, float, Box] | None = None
    hold_lock = False

    if sticky_enabled and previous_box is not None:
        selected = _match_locked_candidate(candidates, previous_box, lock_retain_radius_px)
        if selected is None and (current_time - state.lock_last_seen_time) <= lock_retain_time_s:
            hold_lock = True

    if selected is None and not hold_lock and candidates:
        selected = candidates[0]

    if selected is None:
        if not hold_lock:
            _clear_lock_state(state)
        return None, None, None, False, hold_lock

    _, target_x, target_y, selected_box = selected
    same_target = _boxes_match(previous_box, selected_box, lock_retain_radius_px)
    target_changed = previous_box is not None and not same_target
    projected_smoothed_x = state.smoothed_target_x
    projected_smoothed_y = state.smoothed_target_y

    if projected_smoothed_x is not None and projected_smoothed_y is not None:
        # Project the previously smoothed point into the current frame before blending.
        projected_smoothed_x -= state.applied_mouse_dx
        projected_smoothed_y -= state.applied_mouse_dy

    if target_changed or previous_box is None:
        state.lock_acquired_time = current_time
        state.lock_match_frames = 1
        state.smoothed_target_x = target_x
        state.smoothed_target_y = target_y
    else:
        state.lock_match_frames += 1

    smoothing_alpha = _get_target_smoothing_alpha(
        config,
        state,
        target_x,
        target_y,
        crosshair_x,
        crosshair_y,
        current_time,
    )
    if projected_smoothed_x is None or projected_smoothed_y is None:
        state.smoothed_target_x = target_x
        state.smoothed_target_y = target_y
    else:
        state.smoothed_target_x = ((1.0 - smoothing_alpha) * projected_smoothed_x) + (smoothing_alpha * target_x)
        state.smoothed_target_y = ((1.0 - smoothing_alpha) * projected_smoothed_y) + (smoothing_alpha * target_y)

    state.locked_box = selected_box
    state.lock_last_seen_time = current_time
    state.target_locked = True
    return selected_box, state.smoothed_target_x, state.smoothed_target_y, target_changed, False


def _update_tracker_targets(
    config: Config,
    state: ControlLoopState,
    target_x: float,
    target_y: float,
    crosshair_x: int,
    crosshair_y: int,
    detection_dt: float,
) -> tuple[float, float, bool]:
    predicted_x = target_x
    predicted_y = target_y
    tracker_active = False
    measured_distance = math.hypot(target_x - crosshair_x, target_y - crosshair_y)
    deadzone_px = max(0.0, float(getattr(config, "aim_position_deadzone_px", 3.0)))
    in_deadzone = measured_distance <= deadzone_px

    if not bool(getattr(config, "tracker_enabled", False)):
        _reset_tracker_overlay(config)
        if state.smart_tracker is not None:
            state.smart_tracker.reset()
        return predicted_x, predicted_y, tracker_active

    velocity_alpha = float(getattr(config, "velocity_ema_alpha", 0.35))
    velocity_deadzone = float(getattr(config, "velocity_deadzone_px_per_s", 10.0))
    if state.smart_tracker is None:
        state.smart_tracker = SmartTracker(velocity_alpha, velocity_deadzone)
    else:
        state.smart_tracker.velocity_ema_alpha = min(max(velocity_alpha, 0.0), 1.0)
        state.smart_tracker.velocity_deadzone_px_per_s = max(0.0, velocity_deadzone)

    jump_reset_distance = max(float(getattr(config, "lock_retain_radius_px", 48.0)) * 2.0, 96.0)
    state.smart_tracker.update(target_x, target_y, detection_dt, jump_reset_distance)

    config.tracker_current_x = target_x
    config.tracker_current_y = target_y

    if (
        state.lock_match_frames >= 3
        and not in_deadzone
        and state.smart_tracker.get_speed() >= velocity_deadzone
    ):
        prediction_time_s = max(0.0, float(getattr(config, "prediction_lead_time_s", 0.025)))
        max_prediction_distance_px = float(getattr(config, "prediction_max_distance_px", 32.0))
        predicted_x, predicted_y = state.smart_tracker.get_predicted_position(
            prediction_time_s,
            max_prediction_distance_px,
        )
        config.tracker_predicted_x = predicted_x
        config.tracker_predicted_y = predicted_y
        config.tracker_has_prediction = True
        tracker_active = True
    else:
        config.tracker_predicted_x = target_x
        config.tracker_predicted_y = target_y
        config.tracker_has_prediction = False

    return predicted_x, predicted_y, tracker_active


def _consume_detection_frame(
    config: Config,
    frame: DetectionFrame,
    state: ControlLoopState,
    pid_x: PIDController,
    pid_y: PIDController,
    current_time: float,
    current_perf: float,
) -> bool:
    frame_perf = frame.captured_perf if frame.captured_perf > 0.0 else current_perf
    detection_dt = (
        frame_perf - state.last_detection_update_perf
        if state.last_detection_update_perf > 0.0 and frame_perf > state.last_detection_update_perf
        else max(float(getattr(config, "detect_interval", 0.02) or 0.02), 0.001)
    )
    if state.detection_interval_ema_s <= 0.0:
        state.detection_interval_ema_s = detection_dt
    else:
        interval_alpha = 0.35
        state.detection_interval_ema_s = (
            ((1.0 - interval_alpha) * state.detection_interval_ema_s)
            + (interval_alpha * detection_dt)
        )
    state.last_detection_update_perf = frame_perf
    state.last_processed_sequence = frame.sequence

    selected_box, target_x, target_y, target_changed, hold_lock = _select_target(
        config,
        frame.payload,
        frame.crosshair_x,
        frame.crosshair_y,
        state,
        current_time,
    )

    if hold_lock:
        return False

    if selected_box is None or target_x is None or target_y is None:
        _reset_control_state(config, state, pid_x, pid_y, clear_lock=True)
        return False

    if target_changed:
        pid_x.reset()
        pid_y.reset()
        if state.smart_tracker is not None:
            state.smart_tracker.reset()
        state.bezier_curve_scalar = random.uniform(-1.0, 1.0)

    state.applied_mouse_dx = 0.0
    state.applied_mouse_dy = 0.0
    control_target_x, control_target_y, tracker_active = _update_tracker_targets(
        config,
        state,
        target_x,
        target_y,
        frame.crosshair_x,
        frame.crosshair_y,
        detection_dt,
    )
    state.measured_target_x = target_x
    state.measured_target_y = target_y
    state.control_target_x = control_target_x
    state.control_target_y = control_target_y
    state.tracker_active = tracker_active
    state.last_target_update_perf = frame_perf
    return True


def _apply_control_output(
    config: Config,
    state: ControlLoopState,
    pid_x: PIDController,
    pid_y: PIDController,
    crosshair_x: int,
    crosshair_y: int,
    tick_dt: float,
    current_perf: float,
    current_time: float,
    mouse_method: str,
    processed_new_frame: bool,
) -> tuple[str, float]:
    if (
        not state.target_locked
        or state.measured_target_x is None
        or state.measured_target_y is None
        or state.control_target_x is None
        or state.control_target_y is None
        or state.last_target_update_perf <= 0.0
    ):
        return "idle", 0.0

    target_age_ms = max((current_perf - state.last_target_update_perf) * 1000.0, 0.0)
    hold_ms = max(float(getattr(config, "control_stale_hold_ms", 40.0)), 0.0)
    decay_ms = max(float(getattr(config, "control_stale_decay_ms", 60.0)), 0.0)
    stale_limit_ms = hold_ms + decay_ms

    if target_age_ms > stale_limit_ms:
        _reset_control_state(config, state, pid_x, pid_y, clear_lock=True)
        return "idle", target_age_ms

    phase = "fresh" if processed_new_frame else "hold"
    stale_gain = 1.0
    if not processed_new_frame and target_age_ms > hold_ms:
        phase = "decay"
        stale_gain = 1.0 - ((target_age_ms - hold_ms) / max(decay_ms, 1e-6))
        stale_gain = min(max(stale_gain, 0.0), 1.0)

    measured_error_x = _remaining_error_after_applied_move(
        state.measured_target_x - crosshair_x,
        state.applied_mouse_dx,
    )
    measured_error_y = _remaining_error_after_applied_move(
        state.measured_target_y - crosshair_y,
        state.applied_mouse_dy,
    )
    measured_distance = math.hypot(measured_error_x, measured_error_y)
    deadzone_px = max(0.0, float(getattr(config, "aim_position_deadzone_px", 3.0)))
    if measured_distance <= deadzone_px:
        pid_x.reset()
        pid_y.reset()
        return phase, target_age_ms

    final_error_x = _remaining_error_after_applied_move(
        state.control_target_x - crosshair_x,
        state.applied_mouse_dx,
    )
    final_error_y = _remaining_error_after_applied_move(
        state.control_target_y - crosshair_y,
        state.applied_mouse_dy,
    )
    final_distance = math.hypot(final_error_x, final_error_y)
    control_stage = _determine_control_stage(state, final_distance, current_time)
    state.control_stage = control_stage

    if (
        getattr(config, "bezier_curve_enabled", False)
        and control_stage == "track"
        and not state.tracker_active
        and final_distance > 20.0
    ):
        strength = float(getattr(config, "bezier_curve_strength", 0.35))
        perp_x = -final_error_y
        perp_y = final_error_x
        final_error_x += perp_x * strength * state.bezier_curve_scalar
        final_error_y += perp_y * strength * state.bezier_curve_scalar

    stage_gain = _ACQUIRE_GAIN if control_stage == "acquire" else 1.0
    move_x = int(round(pid_x.update(final_error_x, tick_dt) * stale_gain * stage_gain))
    move_y = int(round(pid_y.update(final_error_y, tick_dt) * stale_gain * stage_gain))

    if control_stage == "acquire":
        if abs(final_error_x) > deadzone_px and abs(move_x) < _ACQUIRE_MIN_MOVE_PX:
            move_x = _move_toward_error(final_error_x, _ACQUIRE_MIN_MOVE_PX)
        if abs(final_error_y) > deadzone_px and abs(move_y) < _ACQUIRE_MIN_MOVE_PX:
            move_y = _move_toward_error(final_error_y, _ACQUIRE_MIN_MOVE_PX)
    elif control_stage == "settle":
        if abs(final_error_x) > deadzone_px and abs(move_x) < _SETTLE_MIN_MOVE_PX:
            move_x = _move_toward_error(final_error_x, _SETTLE_MIN_MOVE_PX, _SETTLE_MAX_MOVE_PX)
        if abs(final_error_y) > deadzone_px and abs(move_y) < _SETTLE_MIN_MOVE_PX:
            move_y = _move_toward_error(final_error_y, _SETTLE_MIN_MOVE_PX, _SETTLE_MAX_MOVE_PX)

    move_x = _clamp_move_to_stage_limit(move_x, final_error_x, control_stage)
    move_y = _clamp_move_to_stage_limit(move_y, final_error_y, control_stage)
    if move_x != 0 or move_y != 0:
        send_mouse_move(move_x, move_y, method=mouse_method)
        state.applied_mouse_dx += move_x
        state.applied_mouse_dy += move_y
    return phase, target_age_ms


def run_control_step(
    config: Config,
    state: ControlLoopState,
    pid_x: PIDController,
    pid_y: PIDController,
    frame: DetectionFrame | None,
    current_perf: float,
    current_time: float,
    tick_dt: float,
) -> ControlStepResult:
    processed_new_frame = False

    if frame is None or not frame.aiming_active:
        _reset_control_state(config, state, pid_x, pid_y, clear_lock=True)
        if frame is not None:
            state.last_processed_sequence = frame.sequence
        return ControlStepResult("idle", 0.0, processed_new_frame)

    if frame.sequence != state.last_processed_sequence:
        processed_new_frame = _consume_detection_frame(
            config,
            frame,
            state,
            pid_x,
            pid_y,
            current_time,
            current_perf,
        )

    phase, target_age_ms = _apply_control_output(
        config,
        state,
        pid_x,
        pid_y,
        frame.crosshair_x,
        frame.crosshair_y,
        tick_dt,
        current_perf,
        current_time,
        state.cached_mouse_move_method,
        processed_new_frame,
    )
    return ControlStepResult(phase, target_age_ms, processed_new_frame)


def _update_control_latency_stats(
    config: Config,
    state: ControlLoopState,
    tick_start_perf: float,
    tick_end_perf: float,
    phase: str,
    target_age_ms: float,
) -> None:
    if not getattr(config, "enable_latency_stats", False):
        return

    alpha = float(getattr(config, "latency_stats_alpha", 0.2))
    alpha = min(max(alpha, 0.01), 1.0)
    tick_ms = (tick_end_perf - tick_start_perf) * 1000.0
    hz = 1000.0 / tick_ms if tick_ms > 0 else 0.0

    if state.latency_ema_tick_ms == 0.0:
        state.latency_ema_tick_ms = tick_ms
        state.latency_ema_hz = hz
        state.latency_ema_target_age_ms = target_age_ms
    else:
        state.latency_ema_tick_ms = ((1.0 - alpha) * state.latency_ema_tick_ms) + (alpha * tick_ms)
        state.latency_ema_hz = ((1.0 - alpha) * state.latency_ema_hz) + (alpha * hz)
        state.latency_ema_target_age_ms = ((1.0 - alpha) * state.latency_ema_target_age_ms) + (alpha * target_age_ms)

    state.latency_phase = phase
    report_interval = float(getattr(config, "latency_stats_interval", 1.0))
    now = time.time()
    if now - state.latency_last_report_time >= report_interval:
        state.latency_last_report_time = now
        logger.info(
            "[Control] tick=%.2fms hz=%.1f target_age=%.1fms phase=%s",
            state.latency_ema_tick_ms,
            state.latency_ema_hz,
            state.latency_ema_target_age_ms,
            state.latency_phase,
        )


def control_loop(config: Config, latest_detection_state: LatestDetectionState) -> None:
    control_hz = max(float(getattr(config, "control_loop_hz", 500.0) or 500.0), 1.0)
    pid_x = PIDController(config.pid_kp_x, config.pid_ki_x, config.pid_kd_x)
    pid_y = PIDController(config.pid_kp_y, config.pid_ki_y, config.pid_kd_y)
    state = ControlLoopState(cached_mouse_move_method=config.mouse_move_method)

    logger.info(
        "Control loop started: control_hz=%.1f stale_hold=%.1fms stale_decay=%.1fms",
        control_hz,
        float(getattr(config, "control_stale_hold_ms", 40.0)),
        float(getattr(config, "control_stale_decay_ms", 60.0)),
    )

    while config.Running:
        try:
            tick_start_perf = time.perf_counter()
            current_time = time.time()
            frame = latest_detection_state.snapshot()
            tick_interval = _resolve_control_tick_interval(config, state, frame)
            tick_dt = tick_interval

            if state.last_tick_perf == 0.0:
                tick_dt = tick_interval
            else:
                tick_dt = max(tick_start_perf - state.last_tick_perf, 1e-4)

            if current_time - state.last_pid_refresh_time > state.pid_check_interval:
                pid_x.Kp, pid_x.Ki, pid_x.Kd = config.pid_kp_x, config.pid_ki_x, config.pid_kd_x
                pid_y.Kp, pid_y.Ki, pid_y.Kd = config.pid_kp_y, config.pid_ki_y, config.pid_kd_y
                state.last_pid_refresh_time = current_time

            if current_time - state.last_method_check_time > state.method_check_interval:
                state.cached_mouse_move_method = config.mouse_move_method
                state.last_method_check_time = current_time

            result = run_control_step(
                config,
                state,
                pid_x,
                pid_y,
                frame,
                tick_start_perf,
                current_time,
                tick_dt,
            )
            tick_end_perf = time.perf_counter()
            _update_control_latency_stats(
                config,
                state,
                tick_start_perf,
                tick_end_perf,
                result.phase,
                result.target_age_ms,
            )

            state.last_tick_perf = tick_start_perf
            remaining = tick_interval - (tick_end_perf - tick_start_perf)
            if remaining > 0:
                time.sleep(remaining)
        except Exception as e:
            logger.error("Control loop error: %s", e)
            traceback.print_exc()
            time.sleep(1.0)

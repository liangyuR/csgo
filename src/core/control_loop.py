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
_SPIN_GUARD_S = 0.002


@dataclass(frozen=True)
class RuntimeControlSettings:
    pid_kp_x: float
    pid_ki_x: float
    pid_kd_x: float
    pid_kp_y: float
    pid_ki_y: float
    pid_kd_y: float
    mouse_move_method: str
    control_loop_hz: float
    detect_interval: float
    sticky_target_enabled: bool
    lock_retain_radius_px: float
    lock_retain_time_s: float
    target_point_smoothing_alpha: float
    tracker_enabled: bool
    prediction_lead_time_s: float
    velocity_ema_alpha: float
    velocity_deadzone_px_per_s: float
    screen_motion_compensation_enabled: bool
    screen_motion_compensation_ratio: float
    prediction_max_distance_px: float
    aim_position_deadzone_px: float
    bezier_curve_enabled: bool
    bezier_curve_strength: float
    control_stale_hold_ms: float
    control_stale_decay_ms: float
    enable_latency_stats: bool
    latency_stats_interval: float
    latency_stats_alpha: float


@dataclass
class ControlLoopState:
    last_tick_perf: float = 0.0
    cached_mouse_move_method: str = "mouse_event"
    runtime_refresh_token: int = -1
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
    last_crosshair_x: int | None = None
    last_crosshair_y: int | None = None
    last_target_screen_x: float | None = None
    last_target_screen_y: float | None = None


@dataclass(frozen=True)
class ControlStepResult:
    phase: str
    target_age_ms: float
    processed_new_frame: bool


def _build_runtime_settings(config: Config) -> RuntimeControlSettings:
    return RuntimeControlSettings(
        pid_kp_x=float(getattr(config, "pid_kp_x", 0.45)),
        pid_ki_x=float(getattr(config, "pid_ki_x", 0.0)),
        pid_kd_x=float(getattr(config, "pid_kd_x", 0.0)),
        pid_kp_y=float(getattr(config, "pid_kp_y", 0.45)),
        pid_ki_y=float(getattr(config, "pid_ki_y", 0.0)),
        pid_kd_y=float(getattr(config, "pid_kd_y", 0.0)),
        mouse_move_method=str(getattr(config, "mouse_move_method", "mouse_event") or "mouse_event"),
        control_loop_hz=max(float(getattr(config, "control_loop_hz", 500.0) or 500.0), 1.0),
        detect_interval=max(float(getattr(config, "detect_interval", 0.02) or 0.02), 0.001),
        sticky_target_enabled=bool(getattr(config, "sticky_target_enabled", True)),
        lock_retain_radius_px=max(float(getattr(config, "lock_retain_radius_px", 48.0)), 0.0),
        lock_retain_time_s=max(float(getattr(config, "lock_retain_time_s", 0.12)), 0.0),
        target_point_smoothing_alpha=min(max(float(getattr(config, "target_point_smoothing_alpha", 0.35)), 0.0), 1.0),
        tracker_enabled=bool(getattr(config, "tracker_enabled", False)),
        prediction_lead_time_s=max(float(getattr(config, "prediction_lead_time_s", 0.018)), 0.0),
        velocity_ema_alpha=min(max(float(getattr(config, "velocity_ema_alpha", 0.45)), 0.0), 1.0),
        velocity_deadzone_px_per_s=max(float(getattr(config, "velocity_deadzone_px_per_s", 10.0)), 0.0),
        screen_motion_compensation_enabled=bool(getattr(config, "screen_motion_compensation_enabled", True)),
        screen_motion_compensation_ratio=min(
            max(float(getattr(config, "screen_motion_compensation_ratio", 1.0)), 0.0),
            1.5,
        ),
        prediction_max_distance_px=max(float(getattr(config, "prediction_max_distance_px", 20.0)), 0.0),
        aim_position_deadzone_px=max(float(getattr(config, "aim_position_deadzone_px", 3.0)), 0.0),
        bezier_curve_enabled=bool(getattr(config, "bezier_curve_enabled", False)),
        bezier_curve_strength=float(getattr(config, "bezier_curve_strength", 0.35)),
        control_stale_hold_ms=max(float(getattr(config, "control_stale_hold_ms", 12.0)), 0.0),
        control_stale_decay_ms=max(float(getattr(config, "control_stale_decay_ms", 24.0)), 0.0),
        enable_latency_stats=bool(getattr(config, "enable_latency_stats", False)),
        latency_stats_interval=max(float(getattr(config, "latency_stats_interval", 1.0)), 0.1),
        latency_stats_alpha=min(max(float(getattr(config, "latency_stats_alpha", 0.2)), 0.01), 1.0),
    )


def _box_to_tuple(box) -> Box:
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

    width = max(0.0, xx2 - xx1)
    height = max(0.0, yy2 - yy1)
    intersection = width * height
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


def _determine_control_stage(state: ControlLoopState, final_distance: float, current_time: float) -> str:
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
    settings: RuntimeControlSettings | None = None,
) -> float:
    if settings is not None:
        base_alpha = settings.target_point_smoothing_alpha
    else:
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
    state.last_crosshair_x = None
    state.last_crosshair_y = None
    state.last_target_screen_x = None
    state.last_target_screen_y = None


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


def _candidate_for_box(box, crosshair_x: int, crosshair_y: int) -> tuple[float, float, float, Box]:
    box_tuple = _box_to_tuple(box)
    center_x, center_y = _box_center(box_tuple)
    distance_sq = _distance_sq(center_x, center_y, crosshair_x, crosshair_y)
    return distance_sq, center_x, center_y, box_tuple


def _select_target(
    config: Config,
    payload: DetectionPayload,
    crosshair_x: int,
    crosshair_y: int,
    state: ControlLoopState,
    current_time: float,
    settings: RuntimeControlSettings | None = None,
) -> tuple[Box | None, float | None, float | None, bool, bool]:
    if settings is not None:
        sticky_enabled = settings.sticky_target_enabled
        lock_retain_radius_px = settings.lock_retain_radius_px
        lock_retain_time_s = settings.lock_retain_time_s
    else:
        sticky_enabled = bool(getattr(config, "sticky_target_enabled", True))
        lock_retain_radius_px = float(getattr(config, "lock_retain_radius_px", 48.0))
        lock_retain_time_s = float(getattr(config, "lock_retain_time_s", 0.12))

    previous_box = state.locked_box
    selected: tuple[float, float, float, Box] | None = None
    hold_lock = False
    nearest_candidate: tuple[float, float, float, Box] | None = None
    best_locked_sort_key: tuple[float, float, float] | None = None
    locked_center_x = 0.0
    locked_center_y = 0.0
    lock_retain_radius_sq = lock_retain_radius_px ** 2

    if sticky_enabled and previous_box is not None:
        locked_center_x, locked_center_y = _box_center(previous_box)

    for box in payload.boxes:
        candidate = _candidate_for_box(box, crosshair_x, crosshair_y)
        distance_sq, center_x, center_y, box_tuple = candidate

        if nearest_candidate is None or distance_sq < nearest_candidate[0]:
            nearest_candidate = candidate

        if not sticky_enabled or previous_box is None:
            continue

        iou = _box_iou(box_tuple, previous_box)
        center_distance_sq = _distance_sq(center_x, center_y, locked_center_x, locked_center_y)
        if iou < 0.2 and center_distance_sq > lock_retain_radius_sq:
            continue

        sort_key = (-iou, center_distance_sq, distance_sq)
        if best_locked_sort_key is None or sort_key < best_locked_sort_key:
            best_locked_sort_key = sort_key
            selected = candidate

    if selected is None and sticky_enabled and previous_box is not None:
        hold_lock = (current_time - state.lock_last_seen_time) <= lock_retain_time_s

    if selected is None and not hold_lock:
        selected = nearest_candidate

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
        settings=settings,
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
    settings: RuntimeControlSettings,
    target_x: float,
    target_y: float,
    crosshair_x: int,
    crosshair_y: int,
    detection_dt: float,
) -> tuple[float, float, bool]:
    predicted_x = target_x
    predicted_y = target_y
    tracker_active = False

    if not settings.tracker_enabled:
        _reset_tracker_overlay(config)
        if state.smart_tracker is not None:
            state.smart_tracker.reset()
        state.last_crosshair_x = crosshair_x
        state.last_crosshair_y = crosshair_y
        state.last_target_screen_x = target_x
        state.last_target_screen_y = target_y
        return predicted_x, predicted_y, tracker_active

    measured_distance = math.hypot(target_x - crosshair_x, target_y - crosshair_y)
    in_deadzone = measured_distance <= settings.aim_position_deadzone_px

    if state.smart_tracker is None:
        state.smart_tracker = SmartTracker(settings.velocity_ema_alpha, settings.velocity_deadzone_px_per_s)
    else:
        state.smart_tracker.velocity_ema_alpha = settings.velocity_ema_alpha
        state.smart_tracker.velocity_deadzone_px_per_s = settings.velocity_deadzone_px_per_s

    motion_dx = None
    motion_dy = None
    if (
        state.last_target_screen_x is not None
        and state.last_target_screen_y is not None
        and state.last_crosshair_x is not None
        and state.last_crosshair_y is not None
    ):
        measured_screen_dx = target_x - state.last_target_screen_x
        measured_screen_dy = target_y - state.last_target_screen_y
        self_motion_dx = crosshair_x - state.last_crosshair_x
        self_motion_dy = crosshair_y - state.last_crosshair_y
        compensation_ratio = settings.screen_motion_compensation_ratio if settings.screen_motion_compensation_enabled else 0.0
        motion_dx = measured_screen_dx + (self_motion_dx * compensation_ratio)
        motion_dy = measured_screen_dy + (self_motion_dy * compensation_ratio)

    jump_reset_distance = max(settings.lock_retain_radius_px * 2.0, 96.0)
    state.smart_tracker.update(
        target_x,
        target_y,
        detection_dt,
        jump_reset_distance,
        motion_dx=motion_dx,
        motion_dy=motion_dy,
    )

    state.last_crosshair_x = crosshair_x
    state.last_crosshair_y = crosshair_y
    state.last_target_screen_x = target_x
    state.last_target_screen_y = target_y

    config.tracker_current_x = target_x
    config.tracker_current_y = target_y

    if (
        state.lock_match_frames >= 3
        and not in_deadzone
        and state.smart_tracker.get_speed() >= settings.velocity_deadzone_px_per_s
    ):
        predicted_x, predicted_y = state.smart_tracker.get_predicted_position(
            settings.prediction_lead_time_s,
            settings.prediction_max_distance_px,
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
    settings: RuntimeControlSettings,
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
        else settings.detect_interval
    )
    if state.detection_interval_ema_s <= 0.0:
        state.detection_interval_ema_s = detection_dt
    else:
        interval_alpha = 0.35
        state.detection_interval_ema_s = ((1.0 - interval_alpha) * state.detection_interval_ema_s) + (interval_alpha * detection_dt)
    state.last_detection_update_perf = frame_perf
    state.last_processed_sequence = frame.sequence

    selected_box, target_x, target_y, target_changed, hold_lock = _select_target(
        config,
        frame.payload,
        frame.crosshair_x,
        frame.crosshair_y,
        state,
        current_time,
        settings=settings,
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
        state.last_crosshair_x = None
        state.last_crosshair_y = None
        state.last_target_screen_x = None
        state.last_target_screen_y = None

    state.applied_mouse_dx = 0.0
    state.applied_mouse_dy = 0.0
    control_target_x, control_target_y, tracker_active = _update_tracker_targets(
        config,
        state,
        settings,
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
    settings: RuntimeControlSettings,
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
    stale_limit_ms = settings.control_stale_hold_ms + settings.control_stale_decay_ms

    if target_age_ms > stale_limit_ms:
        _reset_control_state(config, state, pid_x, pid_y, clear_lock=True)
        return "idle", target_age_ms

    phase = "fresh" if processed_new_frame else "hold"
    stale_gain = 1.0
    if not processed_new_frame and target_age_ms > settings.control_stale_hold_ms:
        phase = "decay"
        stale_gain = 1.0 - ((target_age_ms - settings.control_stale_hold_ms) / max(settings.control_stale_decay_ms, 1e-6))
        stale_gain = min(max(stale_gain, 0.0), 1.0)

    measured_error_x = _remaining_error_after_applied_move(state.measured_target_x - crosshair_x, state.applied_mouse_dx)
    measured_error_y = _remaining_error_after_applied_move(state.measured_target_y - crosshair_y, state.applied_mouse_dy)
    measured_distance = math.hypot(measured_error_x, measured_error_y)
    if measured_distance <= settings.aim_position_deadzone_px:
        pid_x.reset()
        pid_y.reset()
        return phase, target_age_ms

    final_error_x = _remaining_error_after_applied_move(state.control_target_x - crosshair_x, state.applied_mouse_dx)
    final_error_y = _remaining_error_after_applied_move(state.control_target_y - crosshair_y, state.applied_mouse_dy)
    final_distance = math.hypot(final_error_x, final_error_y)
    control_stage = _determine_control_stage(state, final_distance, current_time)
    state.control_stage = control_stage

    if settings.bezier_curve_enabled and control_stage == "track" and not state.tracker_active and final_distance > 20.0:
        perp_x = -final_error_y
        perp_y = final_error_x
        final_error_x += perp_x * settings.bezier_curve_strength * state.bezier_curve_scalar
        final_error_y += perp_y * settings.bezier_curve_strength * state.bezier_curve_scalar

    stage_gain = _ACQUIRE_GAIN if control_stage == "acquire" else 1.0
    move_x = int(round(pid_x.update(final_error_x, tick_dt) * stale_gain * stage_gain))
    move_y = int(round(pid_y.update(final_error_y, tick_dt) * stale_gain * stage_gain))

    if control_stage == "acquire":
        if abs(final_error_x) > settings.aim_position_deadzone_px and abs(move_x) < _ACQUIRE_MIN_MOVE_PX:
            move_x = _move_toward_error(final_error_x, _ACQUIRE_MIN_MOVE_PX)
        if abs(final_error_y) > settings.aim_position_deadzone_px and abs(move_y) < _ACQUIRE_MIN_MOVE_PX:
            move_y = _move_toward_error(final_error_y, _ACQUIRE_MIN_MOVE_PX)
    elif control_stage == "settle":
        if abs(final_error_x) > settings.aim_position_deadzone_px and abs(move_x) < _SETTLE_MIN_MOVE_PX:
            move_x = _move_toward_error(final_error_x, _SETTLE_MIN_MOVE_PX, _SETTLE_MAX_MOVE_PX)
        if abs(final_error_y) > settings.aim_position_deadzone_px and abs(move_y) < _SETTLE_MIN_MOVE_PX:
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
    settings: RuntimeControlSettings | None = None,
) -> ControlStepResult:
    active_settings = settings or _build_runtime_settings(config)
    processed_new_frame = False

    if frame is None or not frame.aiming_active:
        _reset_control_state(config, state, pid_x, pid_y, clear_lock=True)
        if frame is not None:
            state.last_processed_sequence = frame.sequence
        return ControlStepResult("idle", 0.0, processed_new_frame)

    if frame.sequence != state.last_processed_sequence:
        processed_new_frame = _consume_detection_frame(
            config,
            active_settings,
            frame,
            state,
            pid_x,
            pid_y,
            current_time,
            current_perf,
        )

    phase, target_age_ms = _apply_control_output(
        config,
        active_settings,
        state,
        pid_x,
        pid_y,
        frame.crosshair_x,
        frame.crosshair_y,
        tick_dt,
        current_perf,
        current_time,
        active_settings.mouse_move_method,
        processed_new_frame,
    )
    state.cached_mouse_move_method = active_settings.mouse_move_method
    return ControlStepResult(phase, target_age_ms, processed_new_frame)


def _update_control_latency_stats(
    settings: RuntimeControlSettings,
    state: ControlLoopState,
    tick_start_perf: float,
    tick_end_perf: float,
    phase: str,
    target_age_ms: float,
) -> None:
    if not settings.enable_latency_stats:
        return

    tick_ms = (tick_end_perf - tick_start_perf) * 1000.0
    hz = 1000.0 / tick_ms if tick_ms > 0 else 0.0

    if state.latency_ema_tick_ms == 0.0:
        state.latency_ema_tick_ms = tick_ms
        state.latency_ema_hz = hz
        state.latency_ema_target_age_ms = target_age_ms
    else:
        alpha = settings.latency_stats_alpha
        state.latency_ema_tick_ms = ((1.0 - alpha) * state.latency_ema_tick_ms) + (alpha * tick_ms)
        state.latency_ema_hz = ((1.0 - alpha) * state.latency_ema_hz) + (alpha * hz)
        state.latency_ema_target_age_ms = ((1.0 - alpha) * state.latency_ema_target_age_ms) + (alpha * target_age_ms)

    state.latency_phase = phase
    now = time.time()
    if now - state.latency_last_report_time >= settings.latency_stats_interval:
        state.latency_last_report_time = now
        logger.info(
            "[Control] tick=%.2fms hz=%.1f target_age=%.1fms phase=%s",
            state.latency_ema_tick_ms,
            state.latency_ema_hz,
            state.latency_ema_target_age_ms,
            state.latency_phase,
        )


def _wait_precisely(duration_s: float) -> None:
    if duration_s <= 0.0:
        return
    if duration_s > _SPIN_GUARD_S:
        time.sleep(duration_s - _SPIN_GUARD_S)
    target_perf = time.perf_counter() + min(duration_s, _SPIN_GUARD_S)
    while time.perf_counter() < target_perf:
        pass


def _apply_runtime_refresh(
    config: Config,
    state: ControlLoopState,
    pid_x: PIDController,
    pid_y: PIDController,
) -> RuntimeControlSettings:
    settings = _build_runtime_settings(config)
    refresh_token = int(getattr(config, "runtime_refresh_token", 0) or 0)
    if refresh_token != state.runtime_refresh_token:
        pid_x.Kp, pid_x.Ki, pid_x.Kd = settings.pid_kp_x, settings.pid_ki_x, settings.pid_kd_x
        pid_y.Kp, pid_y.Ki, pid_y.Kd = settings.pid_kp_y, settings.pid_ki_y, settings.pid_kd_y
        state.cached_mouse_move_method = settings.mouse_move_method
        if state.runtime_refresh_token >= 0:
            _reset_control_state(config, state, pid_x, pid_y, clear_lock=False)
        state.runtime_refresh_token = refresh_token
    return settings


def control_loop(config: Config, latest_detection_state: LatestDetectionState) -> None:
    initial_settings = _build_runtime_settings(config)
    pid_x = PIDController(initial_settings.pid_kp_x, initial_settings.pid_ki_x, initial_settings.pid_kd_x)
    pid_y = PIDController(initial_settings.pid_kp_y, initial_settings.pid_ki_y, initial_settings.pid_kd_y)
    state = ControlLoopState(cached_mouse_move_method=initial_settings.mouse_move_method)

    logger.info(
        "Control loop started: control_hz=%.1f stale_hold=%.1fms stale_decay=%.1fms",
        initial_settings.control_loop_hz,
        initial_settings.control_stale_hold_ms,
        initial_settings.control_stale_decay_ms,
    )

    while config.Running:
        try:
            tick_start_perf = time.perf_counter()
            current_time = time.time()
            settings = _apply_runtime_refresh(config, state, pid_x, pid_y)
            frame = latest_detection_state.snapshot()
            tick_interval = _resolve_control_tick_interval(settings, state, frame)
            tick_dt = tick_interval if state.last_tick_perf == 0.0 else max(tick_start_perf - state.last_tick_perf, 1e-4)

            result = run_control_step(
                config,
                state,
                pid_x,
                pid_y,
                frame,
                tick_start_perf,
                current_time,
                tick_dt,
                settings=settings,
            )
            tick_end_perf = time.perf_counter()
            _update_control_latency_stats(
                settings,
                state,
                tick_start_perf,
                tick_end_perf,
                result.phase,
                result.target_age_ms,
            )

            state.last_tick_perf = tick_start_perf
            remaining = tick_interval - (tick_end_perf - tick_start_perf)
            if remaining > 0.0:
                _wait_precisely(remaining)
        except Exception as exc:
            logger.error("Control loop error: %s", exc)
            traceback.print_exc()
            time.sleep(1.0)

"""Detection loop that drives capture, preprocess, infer, and publish."""

from __future__ import annotations

import logging
import queue
import time
import traceback
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import win32api
from win_utils import is_key_pressed

from .capture import ScreenCaptureBackend, create_capture_backend
from .detection_state import DetectionFrame, DetectionPayload, LatestDetectionState, empty_detection_payload
from .model_registry import ModelSpec

if TYPE_CHECKING:
    from .config import Config

    class InferenceModel(Protocol):
        provider_name: str

        def warmup(self, iterations: int = 3) -> None: ...

        def detect(
            self,
            frame,
            min_confidence: float,
            offset_x: int = 0,
            offset_y: int = 0,
            target_class_id: int | None = None,
            fov_bounds: tuple[int, int, int, int] | None = None,
        ) -> DetectionPayload: ...


logger = logging.getLogger(__name__)
WARMUP_ITERATIONS = 3
EMPTY_DETECTION_PAYLOAD = empty_detection_payload()
_SPIN_GUARD_S = 0.002


@dataclass(frozen=True)
class DetectionRuntimeSettings:
    width: int
    height: int
    detect_interval: float
    idle_detect_interval: float
    min_confidence: float
    keep_detecting: bool
    always_aim: bool
    fov_follow_mouse: bool
    fov_size: int
    detect_range_size: int
    tracker_enabled: bool
    bezier_curve_enabled: bool
    enable_latency_stats: bool
    latency_stats_interval: float
    latency_stats_alpha: float
    capture_backend: str
    target_class_id: int | None


@dataclass
class DetectionLoopState:
    last_loop_perf: float = 0.0
    latency_last_report_time: float = 0.0
    latency_ema_capture_ms: float = 0.0
    latency_ema_preprocess_ms: float = 0.0
    latency_ema_inference_ms: float = 0.0
    latency_ema_postprocess_ms: float = 0.0
    latency_ema_total_ms: float = 0.0
    latency_ema_fps: float = 0.0
    sequence: int = 0
    runtime_refresh_token: int = -1
    capture_backend_name: str = ""
    region: dict[str, int] = field(default_factory=lambda: {"left": 0, "top": 0, "width": 0, "height": 0})


def _build_runtime_settings(config: Config, model_spec: ModelSpec) -> DetectionRuntimeSettings:
    active_target_class = getattr(config, "active_target_class", model_spec.labels[0])
    if active_target_class not in model_spec.labels:
        active_target_class = model_spec.labels[0]

    return DetectionRuntimeSettings(
        width=int(getattr(config, "width")),
        height=int(getattr(config, "height")),
        detect_interval=max(float(getattr(config, "detect_interval", 0.02) or 0.02), 0.001),
        idle_detect_interval=max(
            float(getattr(config, "idle_detect_interval", getattr(config, "detect_interval", 0.05)) or 0.05),
            0.001,
        ),
        min_confidence=float(getattr(config, "min_confidence", 0.11)),
        keep_detecting=bool(getattr(config, "keep_detecting", True)),
        always_aim=bool(getattr(config, "always_aim", False)),
        fov_follow_mouse=bool(getattr(config, "fov_follow_mouse", True)),
        fov_size=int(getattr(config, "fov_size", model_spec.input_size)),
        detect_range_size=int(getattr(config, "detect_range_size", model_spec.input_size)),
        tracker_enabled=bool(getattr(config, "tracker_enabled", False)),
        bezier_curve_enabled=bool(getattr(config, "bezier_curve_enabled", False)),
        enable_latency_stats=bool(getattr(config, "enable_latency_stats", False)),
        latency_stats_interval=float(getattr(config, "latency_stats_interval", 1.0)),
        latency_stats_alpha=float(getattr(config, "latency_stats_alpha", 0.2)),
        capture_backend=str(getattr(config, "capture_backend", "auto") or "auto").lower(),
        target_class_id=model_spec.label_to_class_id(active_target_class),
    )


def _update_crosshair_position(
    config: Config,
    settings: DetectionRuntimeSettings,
    half_width: int,
    half_height: int,
) -> None:
    if settings.fov_follow_mouse:
        try:
            x, y = win32api.GetCursorPos()
            config.crosshairX, config.crosshairY = x, y
        except (OSError, RuntimeError):
            config.crosshairX, config.crosshairY = half_width, half_height
    else:
        config.crosshairX, config.crosshairY = half_width, half_height


def _replace_queue_payload(target_queue: queue.Queue | None, payload: DetectionPayload) -> None:
    if target_queue is None:
        return
    try:
        while True:
            target_queue.get_nowait()
    except queue.Empty:
        pass

    try:
        target_queue.put_nowait(payload)
    except queue.Full:
        try:
            target_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            target_queue.put_nowait(payload)
        except queue.Full:
            pass


def _clear_queue_payloads(*queues: queue.Queue | None) -> None:
    for target_queue in queues:
        _replace_queue_payload(target_queue, EMPTY_DETECTION_PAYLOAD)


def _publish_detection_frame(
    latest_detection_state: LatestDetectionState,
    state: DetectionLoopState,
    crosshair_x: int,
    crosshair_y: int,
    aiming_active: bool,
    payload: DetectionPayload,
    captured_perf: float,
) -> None:
    latest_detection_state.publish(
        DetectionFrame(
            sequence=state.sequence,
            captured_perf=captured_perf,
            crosshair_x=crosshair_x,
            crosshair_y=crosshair_y,
            aiming_active=aiming_active,
            payload=payload,
        )
    )
    state.sequence += 1


def _calculate_detection_region(
    config: Config | DetectionRuntimeSettings,
    crosshair_x: int,
    crosshair_y: int,
    region: dict[str, int] | None = None,
) -> dict[str, int]:
    width = int(getattr(config, "width"))
    height = int(getattr(config, "height"))
    detection_size = int(getattr(config, "detect_range_size", height))
    detection_size = max(
        int(getattr(config, "fov_size", detection_size)),
        min(width, height, detection_size),
    )
    half_detection_size = detection_size // 2

    max_left = max(0, width - detection_size)
    max_top = max(0, height - detection_size)
    target = region if region is not None else {}
    target["left"] = min(max(0, crosshair_x - half_detection_size), max_left)
    target["top"] = min(max(0, crosshair_y - half_detection_size), max_top)
    target["width"] = max(0, min(detection_size, width))
    target["height"] = max(0, min(detection_size, height))
    return target


def _calculate_fov_bounds(
    crosshair_x: int,
    crosshair_y: int,
    fov_size: int,
) -> tuple[int, int, int, int]:
    fov_half = fov_size // 2
    return (
        crosshair_x - fov_half,
        crosshair_y - fov_half,
        crosshair_x + fov_half,
        crosshair_y + fov_half,
    )


def _update_queues(
    overlay_queue: queue.Queue,
    auto_fire_queue: queue.Queue | None,
    payload: DetectionPayload,
) -> None:
    _replace_queue_payload(overlay_queue, payload)
    _replace_queue_payload(auto_fire_queue, payload)


def _update_latency_stats(
    settings: DetectionRuntimeSettings,
    state: DetectionLoopState,
    loop_start_perf: float,
    capture_end_perf: float,
    preprocess_end_perf: float,
    inference_end_perf: float,
    postprocess_end_perf: float,
) -> None:
    if not settings.enable_latency_stats:
        return

    alpha = min(max(settings.latency_stats_alpha, 0.01), 1.0)

    capture_ms = (capture_end_perf - loop_start_perf) * 1000.0
    preprocess_ms = (preprocess_end_perf - capture_end_perf) * 1000.0
    inference_ms = (inference_end_perf - preprocess_end_perf) * 1000.0
    postprocess_ms = (postprocess_end_perf - inference_end_perf) * 1000.0
    total_ms = (postprocess_end_perf - loop_start_perf) * 1000.0
    fps = 1000.0 / total_ms if total_ms > 0 else 0.0

    if state.latency_ema_total_ms == 0.0:
        state.latency_ema_capture_ms = capture_ms
        state.latency_ema_preprocess_ms = preprocess_ms
        state.latency_ema_inference_ms = inference_ms
        state.latency_ema_postprocess_ms = postprocess_ms
        state.latency_ema_total_ms = total_ms
        state.latency_ema_fps = fps
    else:
        state.latency_ema_capture_ms = ((1.0 - alpha) * state.latency_ema_capture_ms) + (alpha * capture_ms)
        state.latency_ema_preprocess_ms = ((1.0 - alpha) * state.latency_ema_preprocess_ms) + (alpha * preprocess_ms)
        state.latency_ema_inference_ms = ((1.0 - alpha) * state.latency_ema_inference_ms) + (alpha * inference_ms)
        state.latency_ema_postprocess_ms = ((1.0 - alpha) * state.latency_ema_postprocess_ms) + (alpha * postprocess_ms)
        state.latency_ema_total_ms = ((1.0 - alpha) * state.latency_ema_total_ms) + (alpha * total_ms)
        state.latency_ema_fps = ((1.0 - alpha) * state.latency_ema_fps) + (alpha * fps)

    now = time.time()
    if now - state.latency_last_report_time >= settings.latency_stats_interval:
        state.latency_last_report_time = now
        logger.info(
            "[Latency] capture=%.1fms preprocess=%.1fms infer=%.1fms post=%.1fms total=%.1fms fps=%.1f",
            state.latency_ema_capture_ms,
            state.latency_ema_preprocess_ms,
            state.latency_ema_inference_ms,
            state.latency_ema_postprocess_ms,
            state.latency_ema_total_ms,
            state.latency_ema_fps,
        )


def _run_warmup(model: InferenceModel, model_input_size: int) -> None:
    model.warmup(WARMUP_ITERATIONS)
    logger.info(
        "Completed %s warmup inference passes at %dx%d",
        WARMUP_ITERATIONS,
        model_input_size,
        model_input_size,
    )


def _wait_precisely(duration_s: float) -> None:
    if duration_s <= 0.0:
        return

    deadline = time.perf_counter() + duration_s
    if duration_s > _SPIN_GUARD_S:
        time.sleep(duration_s - _SPIN_GUARD_S)
    while time.perf_counter() < deadline:
        pass


def _ensure_runtime_context(
    config: Config,
    model_spec: ModelSpec,
    state: DetectionLoopState,
    capture_backend: ScreenCaptureBackend | None,
) -> tuple[DetectionRuntimeSettings, ScreenCaptureBackend]:
    current_token = int(getattr(config, "runtime_refresh_token", 0) or 0)
    settings = _build_runtime_settings(config, model_spec)
    if (
        capture_backend is not None
        and state.runtime_refresh_token == current_token
        and state.capture_backend_name == settings.capture_backend
    ):
        return settings, capture_backend

    new_backend: ScreenCaptureBackend | None = capture_backend
    if capture_backend is None or state.capture_backend_name != settings.capture_backend:
        if capture_backend is not None:
            capture_backend.close()
        new_backend = create_capture_backend(settings.capture_backend)
        state.capture_backend_name = settings.capture_backend

    state.runtime_refresh_token = current_token
    return settings, new_backend


def ai_logic_loop(
    config: Config,
    model: InferenceModel,
    model_spec: ModelSpec,
    overlay_queue: queue.Queue,
    latest_detection_state: LatestDetectionState,
    auto_fire_boxes_queue: queue.Queue | None = None,
) -> None:
    state = DetectionLoopState()
    capture_backend: ScreenCaptureBackend | None = None
    settings, capture_backend = _ensure_runtime_context(config, model_spec, state, capture_backend)
    _run_warmup(model, model_spec.input_size)

    logger.info(
        "AI loop started: provider=%s capture_backend=%s model_input=%dx%d detect_range=%s latency_stats=%s tracker=%s bezier=%s detect_interval=%.3f",
        getattr(config, "current_provider", getattr(model, "provider_name", "unknown")),
        capture_backend.name,
        model_spec.input_size,
        model_spec.input_size,
        settings.detect_range_size,
        settings.enable_latency_stats,
        settings.tracker_enabled,
        settings.bezier_curve_enabled,
        settings.detect_interval,
    )

    half_width = config.width // 2
    half_height = config.height // 2

    try:
        while config.Running:
            try:
                settings, capture_backend = _ensure_runtime_context(config, model_spec, state, capture_backend)
                loop_start_perf = time.perf_counter()
                capture_end_perf = loop_start_perf
                preprocess_end_perf = loop_start_perf
                inference_end_perf = loop_start_perf
                postprocess_end_perf = loop_start_perf
                state.last_loop_perf = loop_start_perf

                _update_crosshair_position(config, settings, half_width, half_height)
                is_aiming = settings.always_aim or any(is_key_pressed(k) for k in config.AimKeys)

                if not config.AimToggle or (not settings.keep_detecting and not is_aiming):
                    crosshair_x, crosshair_y = config.crosshairX, config.crosshairY
                    _clear_queue_payloads(overlay_queue, auto_fire_boxes_queue)
                    _publish_detection_frame(
                        latest_detection_state,
                        state,
                        crosshair_x,
                        crosshair_y,
                        False,
                        EMPTY_DETECTION_PAYLOAD,
                        loop_start_perf,
                    )
                    _wait_precisely(settings.idle_detect_interval)
                    continue

                crosshair_x, crosshair_y = config.crosshairX, config.crosshairY
                region = _calculate_detection_region(settings, crosshair_x, crosshair_y, state.region)
                config.capture_left = region["left"]
                config.capture_top = region["top"]
                config.capture_width = region["width"]
                config.capture_height = region["height"]
                config.region = region

                if region["width"] <= 0 or region["height"] <= 0:
                    continue

                try:
                    game_frame = capture_backend.grab(region)
                except Exception as e:
                    logger.warning("Screen capture failed with backend %s: %s", capture_backend.name, e)
                    _wait_precisely(settings.idle_detect_interval)
                    continue
                if game_frame is None or game_frame.size == 0:
                    _wait_precisely(0.0005)
                    continue
                capture_end_perf = time.perf_counter()

                preprocess_end_perf = time.perf_counter()
                payload = model.detect(
                    game_frame,
                    min_confidence=settings.min_confidence,
                    offset_x=region["left"],
                    offset_y=region["top"],
                    target_class_id=settings.target_class_id,
                    fov_bounds=_calculate_fov_bounds(crosshair_x, crosshair_y, settings.fov_size),
                )
                inference_end_perf = time.perf_counter()
                postprocess_end_perf = time.perf_counter()

                _update_queues(overlay_queue, auto_fire_boxes_queue, payload)
                _publish_detection_frame(
                    latest_detection_state,
                    state,
                    crosshair_x,
                    crosshair_y,
                    is_aiming,
                    payload,
                    postprocess_end_perf,
                )
                _update_latency_stats(
                    settings,
                    state,
                    loop_start_perf,
                    capture_end_perf,
                    preprocess_end_perf,
                    inference_end_perf,
                    postprocess_end_perf,
                )

                # When aiming, run inference back-to-back at full GPU speed.
                # DXCam's continuous capture thread provides a fresh frame on the
                # next grab() call without blocking, so there is no benefit to
                # sleeping here.  During idle (not aiming), still throttle to
                # avoid unnecessary GPU and CPU usage.
                if not is_aiming:
                    remaining = settings.idle_detect_interval - (time.perf_counter() - loop_start_perf)
                    _wait_precisely(remaining)
            except Exception as e:
                logger.error("AI loop error: %s", e)
                traceback.print_exc()
                time.sleep(1.0)
    finally:
        if capture_backend is not None:
            capture_backend.close()

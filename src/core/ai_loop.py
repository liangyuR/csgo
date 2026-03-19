"""Detection loop that drives capture, preprocess, infer, and publish."""

from __future__ import annotations

import logging
import queue
import time
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import win32api
from win_utils.key_utils import is_key_pressed

from .capture import create_capture_backend
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
    target_class_id: int | None = None


def _update_crosshair_position(config: Config, half_width: int, half_height: int) -> None:
    if config.fov_follow_mouse:
        try:
            x, y = win32api.GetCursorPos()
            config.crosshairX, config.crosshairY = x, y
        except (OSError, RuntimeError):
            config.crosshairX, config.crosshairY = half_width, half_height
    else:
        config.crosshairX, config.crosshairY = half_width, half_height


def _clear_queue_payloads(*queues: queue.Queue) -> None:
    for target_queue in queues:
        if target_queue is None:
            continue
        try:
            while not target_queue.empty():
                target_queue.get_nowait()
        except queue.Empty:
            pass
        target_queue.put(EMPTY_DETECTION_PAYLOAD)


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


def _calculate_detection_region(config: Config, crosshair_x: int, crosshair_y: int) -> dict[str, int]:
    detection_size = int(getattr(config, "detect_range_size", config.height))
    detection_size = max(
        int(config.fov_size),
        min(int(config.width), int(config.height), detection_size),
    )
    half_detection_size = detection_size // 2

    max_left = max(0, int(config.width) - detection_size)
    max_top = max(0, int(config.height) - detection_size)
    region_left = min(max(0, crosshair_x - half_detection_size), max_left)
    region_top = min(max(0, crosshair_y - half_detection_size), max_top)
    region_width = max(0, min(detection_size, int(config.width)))
    region_height = max(0, min(detection_size, int(config.height)))

    return {
        "left": region_left,
        "top": region_top,
        "width": region_width,
        "height": region_height,
    }


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
    for target_queue in (overlay_queue, auto_fire_queue):
        if target_queue is None:
            continue
        try:
            if target_queue.full():
                target_queue.get_nowait()
        except queue.Empty:
            pass
        target_queue.put(payload)


def _update_latency_stats(
    config: Config,
    state: DetectionLoopState,
    loop_start_perf: float,
    capture_end_perf: float,
    preprocess_end_perf: float,
    inference_end_perf: float,
    postprocess_end_perf: float,
) -> None:
    if not getattr(config, "enable_latency_stats", False):
        return

    alpha = float(getattr(config, "latency_stats_alpha", 0.2))
    alpha = min(max(alpha, 0.01), 1.0)

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

    report_interval = float(getattr(config, "latency_stats_interval", 1.0))
    now = time.time()
    if now - state.latency_last_report_time >= report_interval:
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


def _run_warmup(
    model: InferenceModel,
    model_input_size: int,
) -> None:
    model.warmup(WARMUP_ITERATIONS)
    logger.info(
        "Completed %s warmup inference passes at %dx%d",
        WARMUP_ITERATIONS,
        model_input_size,
        model_input_size,
    )


def ai_logic_loop(
    config: Config,
    model: InferenceModel,
    model_spec: ModelSpec,
    overlay_queue: queue.Queue,
    latest_detection_state: LatestDetectionState,
    auto_fire_boxes_queue: queue.Queue | None = None,
) -> None:
    capture_backend = create_capture_backend(getattr(config, "capture_backend", "auto"))
    state = DetectionLoopState()
    _run_warmup(model, model_spec.input_size)

    logger.info(
        "AI loop started: provider=%s capture_backend=%s model_input=%dx%d detect_range=%s latency_stats=%s tracker=%s bezier=%s detect_interval=%.3f",
        getattr(config, "current_provider", getattr(model, "provider_name", "unknown")),
        capture_backend.name,
        model_spec.input_size,
        model_spec.input_size,
        getattr(config, "detect_range_size", "n/a"),
        getattr(config, "enable_latency_stats", False),
        getattr(config, "tracker_enabled", False),
        getattr(config, "bezier_curve_enabled", False),
        float(getattr(config, "detect_interval", 0.0) or 0.0),
    )

    half_width = config.width // 2
    half_height = config.height // 2

    try:
        while config.Running:
            try:
                loop_start_perf = time.perf_counter()
                capture_end_perf = loop_start_perf
                preprocess_end_perf = loop_start_perf
                inference_end_perf = loop_start_perf
                postprocess_end_perf = loop_start_perf
                state.last_loop_perf = loop_start_perf

                _update_crosshair_position(config, half_width, half_height)
                is_aiming = bool(getattr(config, "always_aim", False)) or any(is_key_pressed(k) for k in config.AimKeys)

                if not config.AimToggle or (not config.keep_detecting and not is_aiming):
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
                    time.sleep(0.05)
                    continue

                crosshair_x, crosshair_y = config.crosshairX, config.crosshairY
                region = _calculate_detection_region(config, crosshair_x, crosshair_y)
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
                    continue
                if game_frame is None or game_frame.size == 0:
                    time.sleep(0.001)
                    continue
                capture_end_perf = time.perf_counter()

                preprocess_end_perf = time.perf_counter()
                if state.target_class_id is None or not 0 <= state.target_class_id < len(model_spec.labels):
                    state.target_class_id = model_spec.label_to_class_id(config.active_target_class)
                elif model_spec.class_id_to_label(state.target_class_id) != config.active_target_class:
                    state.target_class_id = model_spec.label_to_class_id(config.active_target_class)

                payload = model.detect(
                    game_frame,
                    min_confidence=config.min_confidence,
                    offset_x=region["left"],
                    offset_y=region["top"],
                    target_class_id=state.target_class_id,
                    fov_bounds=_calculate_fov_bounds(crosshair_x, crosshair_y, config.fov_size),
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
                    config,
                    state,
                    loop_start_perf,
                    capture_end_perf,
                    preprocess_end_perf,
                    inference_end_perf,
                    postprocess_end_perf,
                )

                desired_interval = (
                    config.detect_interval
                    if is_aiming
                    else getattr(config, "idle_detect_interval", config.detect_interval)
                )
                remaining = desired_interval - (time.perf_counter() - loop_start_perf)
                if remaining > 0:
                    time.sleep(remaining)
            except Exception as e:
                logger.error("AI loop error: %s", e)
                traceback.print_exc()
                time.sleep(1.0)
    finally:
        capture_backend.close()

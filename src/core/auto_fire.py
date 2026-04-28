"""Triggerbot loop."""

from __future__ import annotations

import logging
import queue
import time
import traceback
from dataclasses import dataclass
from typing import Any
from typing import TYPE_CHECKING

from win_utils import is_key_pressed, send_mouse_click

if TYPE_CHECKING:
    from .config import Config
    from .detection_state import DetectionPayload


_AUTO_FIRE_TICK_HZ = 500.0
_AUTO_FIRE_TICK_INTERVAL_S = 1.0 / _AUTO_FIRE_TICK_HZ
_AUTO_FIRE_MAX_PAYLOAD_AGE_S = 0.040
_KEY_REFRESH_INTERVAL_S = 0.5


@dataclass
class AutoFireState:
    last_key_state: bool = False
    delay_start_perf: float | None = None
    last_fire_perf: float = 0.0
    cached_payload: DetectionPayload | None = None
    cached_payload_perf: float = 0.0
    auto_fire_key: int = 0
    auto_fire_key2: int | None = None
    last_key_update_perf: float = 0.0


def _unpack_queued_payload(item: Any, fallback_perf: float) -> tuple[DetectionPayload | None, float]:
    if isinstance(item, tuple) and len(item) == 2:
        payload, payload_perf = item
        try:
            return payload, float(payload_perf)
        except (TypeError, ValueError):
            return payload, fallback_perf
    return item, fallback_perf


def _drain_latest_payload(boxes_queue: queue.Queue, fallback_perf: float) -> tuple[DetectionPayload | None, float, bool]:
    latest_payload = None
    latest_perf = fallback_perf
    consumed = False

    while True:
        try:
            item = boxes_queue.get_nowait()
        except queue.Empty:
            break
        latest_payload, latest_perf = _unpack_queued_payload(item, fallback_perf)
        consumed = True

    return latest_payload, latest_perf, consumed


def _payload_has_crosshair_hit(payload: DetectionPayload | None, crosshair_x: int, crosshair_y: int) -> bool:
    if (
        payload is None
        or getattr(payload, "boxes", None) is None
        or getattr(payload.boxes, "shape", (0,))[0] <= 0
    ):
        return False

    for box in payload.boxes:
        x1, y1, x2, y2 = box
        if x1 <= crosshair_x <= x2 and y1 <= crosshair_y <= y2:
            return True
    return False


def _run_auto_fire_step(
    config: Config,
    boxes_queue: queue.Queue,
    state: AutoFireState,
    current_perf: float,
    key_func=is_key_pressed,
    click_func=send_mouse_click,
) -> bool:
    if state.last_key_update_perf <= 0.0 or current_perf - state.last_key_update_perf > _KEY_REFRESH_INTERVAL_S:
        state.auto_fire_key = config.auto_fire_key
        state.auto_fire_key2 = getattr(config, "auto_fire_key2", None)
        state.last_key_update_perf = current_perf

    latest_payload, latest_perf, consumed = _drain_latest_payload(boxes_queue, current_perf)
    if consumed:
        state.cached_payload = latest_payload
        state.cached_payload_perf = latest_perf

    key_state = bool(getattr(config, "always_auto_fire", False)) or key_func(state.auto_fire_key)
    if state.auto_fire_key2:
        key_state = key_state or key_func(state.auto_fire_key2)

    if key_state and not state.last_key_state:
        state.delay_start_perf = current_perf

    fired = False
    if key_state:
        delay_elapsed = (
            state.delay_start_perf is not None
            and (current_perf - state.delay_start_perf) >= config.auto_fire_delay
        )
        payload_fresh = (current_perf - state.cached_payload_perf) <= _AUTO_FIRE_MAX_PAYLOAD_AGE_S
        can_fire = (current_perf - state.last_fire_perf) >= config.auto_fire_interval

        if (
            delay_elapsed
            and payload_fresh
            and can_fire
            and _payload_has_crosshair_hit(state.cached_payload, config.crosshairX, config.crosshairY)
        ):
            click_func(getattr(config, "mouse_click_method", "mouse_event"))
            state.last_fire_perf = current_perf
            fired = True
    else:
        state.delay_start_perf = None
        state.cached_payload = None
        state.cached_payload_perf = 0.0

    state.last_key_state = key_state
    return fired


def auto_fire_loop(config: Config, boxes_queue: queue.Queue) -> None:
    state = AutoFireState()
    logger = logging.getLogger(__name__)

    while config.Running:
        tick_start_perf = time.perf_counter()
        try:
            _run_auto_fire_step(config, boxes_queue, state, tick_start_perf)
            elapsed = time.perf_counter() - tick_start_perf
            remaining = _AUTO_FIRE_TICK_INTERVAL_S - elapsed
            if remaining > 0.0:
                time.sleep(remaining)
        except Exception as e:
            logger.error("AutoFire error: %s", e)
            traceback.print_exc()
            time.sleep(1.0)

"""Triggerbot loop."""

from __future__ import annotations

import logging
import queue
import time
import traceback
from typing import TYPE_CHECKING

from win_utils import is_key_pressed, send_mouse_click

if TYPE_CHECKING:
    from .config import Config
    from .detection_state import DetectionPayload


def auto_fire_loop(config: Config, boxes_queue: queue.Queue) -> None:
    last_key_state = False
    delay_start_time = None
    last_fire_time = 0.0
    cached_payload = None
    last_box_update = 0.0
    logger = logging.getLogger(__name__)

    box_update_interval = 1 / 60
    auto_fire_key = config.auto_fire_key
    auto_fire_key2 = getattr(config, "auto_fire_key2", None)
    last_key_update = 0.0
    key_update_interval = 0.5

    while config.Running:
        try:
            current_time = time.time()
            if current_time - last_key_update > key_update_interval:
                auto_fire_key = config.auto_fire_key
                auto_fire_key2 = getattr(config, "auto_fire_key2", None)
                last_key_update = current_time

            key_state = bool(getattr(config, "always_auto_fire", False)) or is_key_pressed(auto_fire_key)
            if auto_fire_key2:
                key_state = key_state or is_key_pressed(auto_fire_key2)

            if key_state and not last_key_state:
                delay_start_time = current_time

            if key_state:
                if delay_start_time and (current_time - delay_start_time >= config.auto_fire_delay):
                    if current_time - last_fire_time >= config.auto_fire_interval:
                        if current_time - last_box_update >= box_update_interval:
                            try:
                                while True:
                                    cached_payload = boxes_queue.get_nowait()
                                    last_box_update = current_time
                            except queue.Empty:
                                pass
                            except Exception as e:
                                logger.warning("AutoFire queue read failed: %s", e)

                        if (
                            cached_payload is not None
                            and getattr(cached_payload, "boxes", None) is not None
                            and getattr(cached_payload.boxes, "shape", (0,))[0] > 0
                        ):
                            crosshair_x, crosshair_y = config.crosshairX, config.crosshairY
                            for box in cached_payload.boxes:
                                x1, y1, x2, y2 = box
                                if x1 <= crosshair_x <= x2 and y1 <= crosshair_y <= y2:
                                    send_mouse_click(getattr(config, "mouse_click_method", "mouse_event"))
                                    last_fire_time = current_time
                                    break
            else:
                delay_start_time = None
                cached_payload = None

            last_key_state = key_state
            time.sleep(1 / 60)
        except Exception as e:
            logger.error("AutoFire error: %s", e)
            traceback.print_exc()
            time.sleep(1.0)

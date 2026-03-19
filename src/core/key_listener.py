"""Global hotkey listeners."""

from __future__ import annotations

import time

import win32api

from .model_registry import get_default_model_spec
from win_utils import get_vk_name


def _cycle_target_class(config) -> None:
    cycle = list(get_default_model_spec().target_cycle())
    current = getattr(config, "active_target_class", cycle[0])
    try:
        next_index = (cycle.index(current) + 1) % len(cycle)
    except ValueError:
        next_index = 0
    config.active_target_class = cycle[next_index]
    print(f"[快捷键] 当前目标类别: {config.active_target_class}")


def aim_toggle_key_listener(config, update_gui_callback=None):
    last_toggle_state = False
    last_cycle_state = False
    toggle_key_code = getattr(config, "aim_toggle_key", 0x78)
    cycle_key_code = getattr(config, "cycle_target_key", 0x77)
    sleep_interval = 0.03

    while True:
        try:
            current_toggle_key = getattr(config, "aim_toggle_key", 0x78)
            current_cycle_key = getattr(config, "cycle_target_key", 0x77)
            if current_toggle_key != toggle_key_code:
                toggle_key_code = current_toggle_key
                print(f"[快捷键] 瞄准开关键: {get_vk_name(toggle_key_code)}")
            if current_cycle_key != cycle_key_code:
                cycle_key_code = current_cycle_key
                print(f"[快捷键] 目标类别切换键: {get_vk_name(cycle_key_code)}")

            toggle_state = bool(win32api.GetAsyncKeyState(toggle_key_code) & 0x8000)
            if toggle_state and not last_toggle_state:
                old_state = config.AimToggle
                config.AimToggle = not config.AimToggle
                print(f"[快捷键] 自动瞄准: {old_state} -> {config.AimToggle}")
                if update_gui_callback:
                    update_gui_callback(config.AimToggle)
            last_toggle_state = toggle_state

            cycle_state = bool(win32api.GetAsyncKeyState(cycle_key_code) & 0x8000)
            if cycle_state and not last_cycle_state:
                _cycle_target_class(config)
            last_cycle_state = cycle_state
        except Exception as e:
            print(f"[快捷键监听错误] {e}")
            import traceback

            traceback.print_exc()

        time.sleep(sleep_interval)

"""Global hotkey listener for in-game aim toggle and program exit.

Uses the `keyboard` library which works even when the game window has focus.

Supported trigger modes per key:
- "toggle"   : each press flips a boolean state (default for aim enable key)
- "hold"     : active while the key is held down (press-to-hold)
- "exit"     : immediately sets the stop flag (default for exit key)

Usage example:
    from csgo_vision_demo.hotkey import HotkeyManager

    mgr = HotkeyManager(toggle_key="f2", exit_key="f10", mode="toggle")
    mgr.start()

    while mgr.running:
        if mgr.aim_active:
            ...   # do mouse movement
        time.sleep(0.001)

    mgr.stop()
"""
from __future__ import annotations

import ctypes
import threading
import time
from typing import Callable, Optional


VK_CODE_MAP = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "caps lock": 0x14,
    "esc": 0x1B,
    "space": 0x20,
    "page up": 0x21,
    "page down": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
}
for index in range(1, 13):
    VK_CODE_MAP[f"f{index}"] = 0x6F + index
for char_code in range(ord("A"), ord("Z") + 1):
    VK_CODE_MAP[chr(char_code).lower()] = char_code
for digit in range(10):
    VK_CODE_MAP[str(digit)] = 0x30 + digit


class _Win32HotkeyBackend:
    def __init__(self, manager: "HotkeyManager") -> None:
        self._manager = manager
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="hotkey-poll")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        toggle_vk = _key_to_vk(self._manager.toggle_key)
        exit_vk = _key_to_vk(self._manager.exit_key)
        if toggle_vk is None or exit_vk is None:
            raise RuntimeError(
                f"Unsupported hotkey(s) for Win32 backend: toggle={self._manager.toggle_key!r}, "
                f"exit={self._manager.exit_key!r}"
            )

        toggle_down = False
        exit_down = False

        while not self._stop_event.is_set() and self._manager.running:
            toggle_pressed = bool(user32.GetAsyncKeyState(toggle_vk) & 0x8000)
            exit_pressed = bool(user32.GetAsyncKeyState(exit_vk) & 0x8000)

            if self._manager.mode == "toggle":
                if toggle_pressed and not toggle_down:
                    self._manager._on_toggle_press()
                toggle_down = toggle_pressed
            else:
                if toggle_pressed and not toggle_down:
                    self._manager._on_hold_down()
                elif not toggle_pressed and toggle_down:
                    self._manager._on_hold_up()
                toggle_down = toggle_pressed

            if exit_pressed and not exit_down:
                self._manager._on_exit_press()
            exit_down = exit_pressed
            time.sleep(0.01)


class _KeyboardHotkeyBackend:
    def __init__(self, manager: "HotkeyManager") -> None:
        self._manager = manager

    def start(self) -> None:
        try:
            import keyboard as kb
        except ImportError as exc:
            raise RuntimeError(
                "keyboard is not installed. Run: pip install keyboard"
            ) from exc

        if self._manager.mode == "toggle":
            kb.add_hotkey(self._manager.toggle_key, self._manager._on_toggle_press, suppress=False)
        else:
            kb.on_press_key(self._manager.toggle_key, self._manager._on_hold_down, suppress=False)
            kb.on_release_key(self._manager.toggle_key, self._manager._on_hold_up, suppress=False)

        kb.add_hotkey(self._manager.exit_key, self._manager._on_exit_press, suppress=False)

    def stop(self) -> None:
        try:
            import keyboard as kb
            kb.unhook_all()
        except Exception:
            pass


def _key_to_vk(key: str) -> int | None:
    normalized = key.strip().lower()
    if normalized in VK_CODE_MAP:
        return VK_CODE_MAP[normalized]
    if len(normalized) == 1 and normalized.isprintable():
        return ord(normalized.upper())
    return None


class HotkeyManager:
    """Manages global hotkeys for aim toggle and program exit.

    Args:
        toggle_key: Key name (keyboard library format) to toggle aiming.
            Examples: "f2", "caps lock", "x", "insert".
        exit_key:   Key name to request program exit.
        mode:       "toggle" (each press flips aim_active) or
                    "hold"   (aim_active is True only while key is held).
        on_exit:    Optional callback invoked when exit_key is pressed.
    """

    def __init__(
        self,
        toggle_key: str = "f2",
        exit_key: str = "f10",
        mode: str = "toggle",
        on_exit: Optional[Callable[[], None]] = None,
    ) -> None:
        if mode not in ("toggle", "hold"):
            raise ValueError(f"mode must be 'toggle' or 'hold', got {mode!r}")

        self.toggle_key = toggle_key
        self.exit_key = exit_key
        self.mode = mode
        self.on_exit = on_exit

        self._aim_active: bool = False
        self._running: bool = False
        self._lock = threading.Lock()
        self._backend: _Win32HotkeyBackend | _KeyboardHotkeyBackend | None = None

    # ------------------------------------------------------------------
    # State properties (thread-safe reads)
    # ------------------------------------------------------------------

    @property
    def aim_active(self) -> bool:
        with self._lock:
            return self._aim_active

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Register hotkeys and mark manager as running."""
        with self._lock:
            self._running = True

        if hasattr(ctypes, "windll") and getattr(ctypes.windll, "user32", None) is not None:
            self._backend = _Win32HotkeyBackend(self)
            print("[hotkey] Using Win32 polling backend.")
        else:
            self._backend = _KeyboardHotkeyBackend(self)
            print("[hotkey] Using keyboard hook backend.")
        self._backend.start()

    def stop(self) -> None:
        """Unregister all hotkeys and mark manager as stopped."""
        if self._backend is not None:
            try:
                self._backend.stop()
            except Exception:
                pass
            self._backend = None
        with self._lock:
            self._running = False
            self._aim_active = False

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _on_toggle_press(self) -> None:
        with self._lock:
            self._aim_active = not self._aim_active
            aim_active = self._aim_active
        print(f"[hotkey] Toggle {self.toggle_key} -> aim {'ON' if aim_active else 'OFF'}")

    def _on_hold_down(self, _event=None) -> None:
        with self._lock:
            self._aim_active = True
        print(f"[hotkey] Hold {self.toggle_key} -> aim ON")

    def _on_hold_up(self, _event=None) -> None:
        with self._lock:
            self._aim_active = False
        print(f"[hotkey] Hold {self.toggle_key} released -> aim OFF")

    def _on_exit_press(self) -> None:
        with self._lock:
            self._running = False
            self._aim_active = False
        print(f"[hotkey] Exit {self.exit_key} pressed.")
        if self.on_exit is not None:
            self.on_exit()

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

import threading
from typing import Callable, Optional


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
        try:
            import keyboard as kb
        except ImportError as exc:
            raise RuntimeError(
                "keyboard is not installed. Run: pip install keyboard"
            ) from exc

        with self._lock:
            self._running = True

        if self.mode == "toggle":
            kb.add_hotkey(self.toggle_key, self._on_toggle_press, suppress=False)
        else:
            kb.on_press_key(self.toggle_key, self._on_hold_down, suppress=False)
            kb.on_release_key(self.toggle_key, self._on_hold_up, suppress=False)

        kb.add_hotkey(self.exit_key, self._on_exit_press, suppress=False)

    def stop(self) -> None:
        """Unregister all hotkeys and mark manager as stopped."""
        try:
            import keyboard as kb
            kb.unhook_all()
        except Exception:
            pass
        with self._lock:
            self._running = False
            self._aim_active = False

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _on_toggle_press(self) -> None:
        with self._lock:
            self._aim_active = not self._aim_active

    def _on_hold_down(self, _event=None) -> None:
        with self._lock:
            self._aim_active = True

    def _on_hold_up(self, _event=None) -> None:
        with self._lock:
            self._aim_active = False

    def _on_exit_press(self) -> None:
        with self._lock:
            self._running = False
            self._aim_active = False
        if self.on_exit is not None:
            self.on_exit()

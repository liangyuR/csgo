"""Mouse control module for Windows.

Sends relative mouse movement via ctypes SendInput -- no extra dependencies.
SendInput bypasses SetCursorPos (which does not affect raw-input games) and is
required for CS2/CSGO which use raw mouse input.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as _wt


# ------------------------------------------------------------------
# Win32 structures for SendInput
# ------------------------------------------------------------------

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_MOVE_NOCOALESCE = 0x2000


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", _wt.LONG),
        ("dy", _wt.LONG),
        ("mouseData", _wt.DWORD),
        ("dwFlags", _wt.DWORD),
        ("time", _wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type", _wt.DWORD),
        ("_input", _INPUT_UNION),
    ]


INPUT_MOUSE = 0


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def move_relative(dx: float, dy: float) -> None:
    """Send a relative mouse movement of (dx, dy) pixels via SendInput.

    Values are rounded to integers. Zero-delta axes are still sent so the
    single SendInput call is atomic.
    """
    ix = int(round(dx))
    iy = int(round(dy))
    if ix == 0 and iy == 0:
        return

    inp = _INPUT(
        type=INPUT_MOUSE,
        _input=_INPUT_UNION(
            mi=_MOUSEINPUT(
                dx=ix,
                dy=iy,
                mouseData=0,
                dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_MOVE_NOCOALESCE,
                time=0,
                dwExtraInfo=None,
            )
        ),
    )
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


class MouseController:
    """Wraps raw SendInput with an optional sensitivity scalar.

    Args:
        sensitivity: multiplier applied to every move delta.  Tune this to
            match the in-game sensitivity so 1 pixel of aim offset maps to
            roughly 1 pixel of crosshair movement on screen.
    """

    def __init__(self, sensitivity: float = 1.0) -> None:
        self.sensitivity = float(sensitivity)

    def move(self, dx: float, dy: float) -> None:
        """Move mouse by (dx, dy) after applying sensitivity scaling."""
        move_relative(dx * self.sensitivity, dy * self.sensitivity)

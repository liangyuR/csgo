"""Block physical mouse movement while allowing app-generated aim movement."""

from __future__ import annotations

import atexit
import ctypes
import logging
import threading
import time

logger = logging.getLogger(__name__)

HC_ACTION = 0
WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_QUIT = 0x0012
LLMHF_INJECTED = 0x00000001
LLMHF_LOWER_IL_INJECTED = 0x00000002


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_ulong),
        ("pt", POINT),
    ]


_callback_factory = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
LowLevelMouseProc = _callback_factory(
    ctypes.c_ssize_t,
    ctypes.c_int,
    ctypes.c_size_t,
    ctypes.c_ssize_t,
)


def _is_mouse_move_message(message: int) -> bool:
    return int(message) == WM_MOUSEMOVE


def _is_injected_mouse_event(flags: int) -> bool:
    return bool(int(flags) & (LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED))


class MouseMoveBlocker:
    """Low-level mouse hook that suppresses physical mouse movement only."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._blocked = False
        self._allow_program_move_until = 0.0
        self._hook_handle = ctypes.c_void_p()
        self._hook_thread: threading.Thread | None = None
        self._hook_thread_id = 0
        self._callback = LowLevelMouseProc(self._hook_proc)
        self._start_failed = False

    def start(self) -> bool:
        if not hasattr(ctypes, "windll"):
            return False

        with self._lock:
            if self._hook_handle:
                return True
            if self._hook_thread is not None and self._hook_thread.is_alive():
                return True
            if self._start_failed:
                return False

            ready = threading.Event()
            self._hook_thread = threading.Thread(
                target=self._hook_thread_main,
                args=(ready,),
                name="MouseMoveBlocker",
                daemon=True,
            )
            self._hook_thread.start()

        ready.wait(timeout=1.0)
        with self._lock:
            return bool(self._hook_handle)

    def stop(self) -> None:
        if not hasattr(ctypes, "windll"):
            return

        with self._lock:
            thread = self._hook_thread
            thread_id = self._hook_thread_id
            self._blocked = False

        if thread_id:
            ctypes.windll.user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

        with self._lock:
            self._hook_thread = None
            self._hook_thread_id = 0
            self._hook_handle = ctypes.c_void_p()
            self._allow_program_move_until = 0.0
            self._start_failed = False

    def set_blocked(self, active: bool) -> None:
        with self._lock:
            self._blocked = bool(active)
        if active:
            self.start()

    def is_blocked(self) -> bool:
        with self._lock:
            return self._blocked

    def allow_program_mouse_move(self, duration_s: float = 0.025) -> None:
        until = time.perf_counter() + max(float(duration_s), 0.0)
        with self._lock:
            self._allow_program_move_until = max(self._allow_program_move_until, until)

    def should_block_event(
        self,
        n_code: int,
        message: int,
        flags: int = 0,
        now: float | None = None,
    ) -> bool:
        if int(n_code) != HC_ACTION or not _is_mouse_move_message(message):
            return False
        if _is_injected_mouse_event(flags):
            return False

        current = time.perf_counter() if now is None else float(now)
        with self._lock:
            if not self._blocked:
                return False
            return current > self._allow_program_move_until

    def _hook_thread_main(self, ready: threading.Event) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        kernel32.GetCurrentThreadId.restype = ctypes.c_ulong
        kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            LowLevelMouseProc,
            ctypes.c_void_p,
            ctypes.c_ulong,
        ]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.UnhookWindowsHookEx.restype = ctypes.c_bool
        user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        user32.GetMessageW.restype = ctypes.c_int
        user32.PostThreadMessageW.argtypes = [ctypes.c_ulong, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.PostThreadMessageW.restype = ctypes.c_bool

        self._hook_thread_id = kernel32.GetCurrentThreadId()

        hook = user32.SetWindowsHookExW(
            WH_MOUSE_LL,
            self._callback,
            kernel32.GetModuleHandleW(None),
            0,
        )
        with self._lock:
            self._hook_handle = ctypes.c_void_p(hook)
            self._start_failed = not bool(hook)
        ready.set()

        if not hook:
            logger.warning("Failed to install low-level mouse move blocker hook")
            return

        msg = MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnhookWindowsHookEx(hook)
            with self._lock:
                self._hook_handle = ctypes.c_void_p()

    def _hook_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        flags = 0
        if n_code == HC_ACTION and l_param:
            mouse_info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            flags = int(mouse_info.flags)

        if self.should_block_event(n_code, int(w_param), flags):
            return 1

        return ctypes.windll.user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)


mouse_move_blocker = MouseMoveBlocker()


def start_mouse_move_blocker() -> bool:
    return mouse_move_blocker.start()


def stop_mouse_move_blocker() -> None:
    mouse_move_blocker.stop()


def set_user_mouse_move_blocked(active: bool) -> None:
    mouse_move_blocker.set_blocked(active)


def is_user_mouse_move_blocked() -> bool:
    return mouse_move_blocker.is_blocked()


def allow_program_mouse_move(duration_s: float = 0.025) -> None:
    mouse_move_blocker.allow_program_mouse_move(duration_s)


atexit.register(stop_mouse_move_blocker)

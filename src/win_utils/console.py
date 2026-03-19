# console.py - 終端視窗控制模組
"""Windows 終端視窗控制"""

import ctypes


def get_console_window():
    """獲取當前控制台視窗的句柄"""
    try:
        kernel32 = ctypes.windll.kernel32
        return kernel32.GetConsoleWindow()
    except Exception as e:
        print(f"[終端控制] 獲取控制台視窗失敗: {e}")
        return None


def show_console():
    """顯示終端視窗"""
    try:
        hwnd = get_console_window()
        if hwnd:
            user32 = ctypes.windll.user32
            SW_SHOW = 5
            user32.ShowWindow(hwnd, SW_SHOW)
            print("[終端控制] 終端視窗已顯示")
            return True
        else:
            print("[終端控制] 無法獲取終端視窗句柄")
            return False
    except Exception as e:
        print(f"[終端控制] 顯示終端視窗失敗: {e}")
        return False


def hide_console():
    """隱藏終端視窗"""
    try:
        hwnd = get_console_window()
        if hwnd:
            user32 = ctypes.windll.user32
            SW_HIDE = 0
            user32.ShowWindow(hwnd, SW_HIDE)
            return True
        else:
            return False
    except Exception as e:
        print(f"[終端控制] 隱藏終端視窗失敗: {e}")
        return False


def is_console_visible():
    """檢查終端視窗是否可見"""
    try:
        hwnd = get_console_window()
        if hwnd:
            user32 = ctypes.windll.user32
            return user32.IsWindowVisible(hwnd)
        return False
    except Exception:
        return False


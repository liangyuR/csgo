# key_utils.py - 按鍵檢測模組
"""按鍵狀態檢測"""

import win32api


def is_key_pressed(key_code):
    """檢查指定按鍵是否被按下"""
    return win32api.GetAsyncKeyState(key_code) & 0x8000 != 0


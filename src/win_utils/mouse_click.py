# mouse_click.py - 滑鼠點擊模組
"""滑鼠點擊相關函數 (DDXoft)"""

import time
import logging

from .ddxoft_mouse import ddxoft_mouse


logger = logging.getLogger(__name__)


def send_mouse_click_ddxoft():
    """ddxoft 左鍵點擊"""
    if not ddxoft_mouse.ensure_initialized():
        return False
    return ddxoft_mouse.click_left()


def send_mouse_click(method=None):
    """統一的滑鼠點擊函數 (DDXoft)"""
    try:
        return send_mouse_click_ddxoft()
    except Exception:
        return False


def test_mouse_click_methods():
    """測試 ddxoft 滑鼠點擊"""
    print("[測試] 開始測試 ddxoft 滑鼠點擊...")
    try:
        success = send_mouse_click_ddxoft()
        if success:
            print("[測試] ddxoft 點擊成功")
        else:
            print("[測試] ✗ ddxoft 點擊失敗")
    except Exception as e:
        print(f"[測試] ✗ ddxoft 點擊異常: {e}")
    time.sleep(0.5)
    print("[測試] 滑鼠點擊測試完成")

# mouse_click.py - 滑鼠點擊模組
"""滑鼠點擊相關函數"""

import time
import logging
import win32api
import win32con

from .ddxoft_mouse import ddxoft_mouse


_hardware_not_impl_warned = False
logger = logging.getLogger(__name__)


# ===== 滑鼠點擊函數 =====

def send_mouse_click_sendinput():
    """SendInput 左鍵點擊"""
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def send_mouse_click_hardware():
    """硬件層級左鍵點擊
    
    TODO: 實現真正的硬件層級滑鼠點擊
    目前暫時使用 SendInput 方式，未來可考慮整合 ddxoft 或其他驅動級方案。
    """
    global _hardware_not_impl_warned
    if not _hardware_not_impl_warned:
        logger.warning("hardware 模式尚未實作，已回退為 sendinput")
        _hardware_not_impl_warned = True
    # 暫時使用和 sendinput 相同的實現
    send_mouse_click_sendinput()


def send_mouse_click_mouse_event():
    """mouse_event 左鍵點擊"""
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def send_mouse_click_ddxoft():
    """ddxoft 左鍵點擊"""
    try:
        if not ddxoft_mouse.ensure_initialized():
            send_mouse_click_mouse_event()
            return True

        if ddxoft_mouse.click_left():
            return True
        else:
            # 如果 ddxoft 失敗，靜默回退到 mouse_event 方式
            send_mouse_click_mouse_event()
            return True
    except Exception:
        send_mouse_click_mouse_event()
        return True


def send_mouse_click(method="ddxoft"):
    """
    統一的滑鼠點擊函數，支援多種方式
    method 選項:
    - "sendinput": SendInput (原始方式，容易被檢測)
    - "hardware": 硬件層級 (較隱蔽)
    - "mouse_event": mouse_event (很隱蔽)
    - "ddxoft": ddxoft (最隱蔽，需要 ddxoft.dll)
    - "xbox": Xbox 360 虛擬手把 (RT 扳機)
    """
    try:
        if method == "sendinput":
            send_mouse_click_sendinput()
        elif method == "hardware":
            send_mouse_click_hardware()
        elif method == "mouse_event":
            send_mouse_click_mouse_event()
        elif method == "ddxoft":
            return send_mouse_click_ddxoft()
        elif method == "xbox":
            from .xbox_controller import send_mouse_click_xbox
            return send_mouse_click_xbox()
        else:
            return send_mouse_click_ddxoft()  # 默認方式
        return True
    except Exception:
        # 靜默回退到 mouse_event
        try:
            send_mouse_click_mouse_event()
            return True
        except Exception:
            return False


def test_mouse_click_methods():
    """測試所有滑鼠點擊方式"""
    print("[測試] 開始測試所有滑鼠點擊方式...")
    
    methods = ["mouse_event", "sendinput", "hardware", "ddxoft"]
    
    for method in methods:
        print(f"[測試] 測試 {method} 點擊方式...")
        try:
            success = send_mouse_click(method)
            if success:
                print(f"[測試] {method} 點擊成功")
            else:
                print(f"[測試] ✗ {method} 點擊失敗")
        except Exception as e:
            print(f"[測試] ✗ {method} 點擊異常: {e}")
        
        time.sleep(0.5)  # 延遲0.5秒避免連點
    
    print("[測試] 滑鼠點擊測試完成")


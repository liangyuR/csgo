# win_utils/__init__.py - Windows 工具包
"""
Windows 工具包 - 提供滑鼠控制、按鍵檢測、管理員權限、終端控制等功能

模組結構:
- vk_codes: 虛擬按鍵碼與翻譯
- ddxoft_mouse: DDXoft 滑鼠控制
- mouse_click: 滑鼠點擊函數
- key_utils: 按鍵檢測
- admin: 管理員權限管理
- console: 終端視窗控制
"""

# 虛擬按鍵碼
from .vk_codes import (
    VK_CODE_MAP,
    VK_TRANSLATIONS,
    get_vk_name,
)

# 滑鼠移動 - ddxoft
from .ddxoft_mouse import (
    DDXoftMouse,
    ddxoft_mouse,
    send_mouse_move_ddxoft,
    ensure_ddxoft_ready,
    test_ddxoft_functions,
    get_ddxoft_statistics,
    print_ddxoft_statistics,
    reset_ddxoft_statistics,
)

# 滑鼠點擊
from .mouse_click import (
    send_mouse_click_ddxoft,
    send_mouse_click,
    test_mouse_click_methods,
)

# 按鍵檢測
from .key_utils import is_key_pressed

# 管理員權限
from .admin import (
    is_admin,
    ensure_admin_for_feature,
    request_admin_privileges,
    check_and_request_admin,
)

# 終端控制
from .console import (
    get_console_window,
    show_console,
    hide_console,
    is_console_visible,
)


# ===== 主要滑鼠移動函數 =====

def send_mouse_move(dx, dy, method=None):
    """主要滑鼠移動函數 (DDXoft)"""
    if abs(dx) < 1 and abs(dy) < 1:
        return
    send_mouse_move_ddxoft(dx, dy)


# 公開的 API 列表
__all__ = [
    # 虛擬按鍵碼
    'VK_CODE_MAP',
    'VK_TRANSLATIONS',
    'get_vk_name',

    # 滑鼠移動
    'send_mouse_move',
    'send_mouse_move_ddxoft',

    # ddxoft
    'DDXoftMouse',
    'ddxoft_mouse',
    'ensure_ddxoft_ready',
    'test_ddxoft_functions',
    'get_ddxoft_statistics',
    'print_ddxoft_statistics',
    'reset_ddxoft_statistics',

    # 滑鼠點擊
    'send_mouse_click',
    'send_mouse_click_ddxoft',
    'test_mouse_click_methods',

    # 按鍵檢測
    'is_key_pressed',

    # 管理員權限
    'is_admin',
    'ensure_admin_for_feature',
    'request_admin_privileges',
    'check_and_request_admin',

    # 終端控制
    'get_console_window',
    'show_console',
    'hide_console',
    'is_console_visible',
]

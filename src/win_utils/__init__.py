# win_utils/__init__.py - Windows 工具包
"""
Windows 工具包 - 提供滑鼠控制、按鍵檢測、管理員權限、終端控制等功能

模組結構:
- vk_codes: 虛擬按鍵碼與翻譯
- mouse_move: 滑鼠移動基礎函數

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

# 滑鼠移動 - 基礎
from .mouse_move import (
    MOUSEINPUT,
    INPUT,
    INPUT_MOUSE,
    MOUSEEVENTF_MOVE,
    send_mouse_move_sendinput,
    send_mouse_move_mouse_event,
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

# 滑鼠移動 - Arduino Leonardo
from .arduino_mouse import (
    ArduinoMouse,
    arduino_mouse,
    send_mouse_move_arduino,
    get_available_com_ports,
    connect_arduino,
    disconnect_arduino,
    is_arduino_connected,
)

# 滑鼠移動 - Xbox 360 虛擬手把
from .xbox_controller import (
    XboxController,
    xbox_controller,
    send_mouse_move_xbox,
    send_mouse_click_xbox,
    connect_xbox,
    disconnect_xbox,
    is_xbox_connected,
    is_xbox_available,
    set_xbox_sensitivity,
    set_xbox_deadzone,
    get_xbox_statistics,
)

# 滑鼠點擊
from .mouse_click import (
    send_mouse_click_sendinput,
    send_mouse_click_hardware,
    send_mouse_click_mouse_event,
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

def send_mouse_move(dx, dy, method="mouse_event"):
    """
    主要滑鼠移動函數
    method 選項:
    - "sendinput": SendInput (原始方式，容易被檢測)
    - "mouse_event": mouse_event (預設，穩定且安全)
    - "ddxoft": ddxoft (最隱蔽，需要 ddxoft.dll，但可能導致藍屏)
    - "arduino": Arduino Leonardo (USB HID，非常隱蔽)
    - "xbox": Xbox 360 虛擬手把 (透過 ViGEmBus，適用手把遊戲)
    """
    if abs(dx) < 1 and abs(dy) < 1:
        return  # 移動量太小，跳過
    
    if method == "sendinput":
        send_mouse_move_sendinput(dx, dy)
    elif method == "mouse_event":
        send_mouse_move_mouse_event(dx, dy)
    elif method == "ddxoft":
        send_mouse_move_ddxoft(dx, dy)
    elif method == "arduino":
        send_mouse_move_arduino(dx, dy)
    elif method == "xbox":
        send_mouse_move_xbox(dx, dy)
    else:
        # 默認使用 mouse_event 方式（安全穩定）
        send_mouse_move_mouse_event(dx, dy)


# 公開的 API 列表
__all__ = [
    # 虛擬按鍵碼
    'VK_CODE_MAP',
    'VK_TRANSLATIONS',
    'get_vk_name',
    
    # 滑鼠移動
    'MOUSEINPUT',
    'INPUT',
    'INPUT_MOUSE',
    'MOUSEEVENTF_MOVE',
    'send_mouse_move',
    'send_mouse_move_sendinput',
    'send_mouse_move_mouse_event',
    'send_mouse_move_ddxoft',
    'send_mouse_move_arduino',
    'send_mouse_move_xbox',
    
    # 控制器類
    'DDXoftMouse',
    'XboxController',
    'xbox_controller',
    'ddxoft_mouse',
    
    # ddxoft 公共接口
    'ensure_ddxoft_ready',
    'test_ddxoft_functions',
    'get_ddxoft_statistics',
    'print_ddxoft_statistics',
    'reset_ddxoft_statistics',
    
    # Arduino 控制
    'ArduinoMouse',
    'arduino_mouse',
    'get_available_com_ports',
    'connect_arduino',
    'disconnect_arduino',
    'is_arduino_connected',
    
    # Xbox 360 虛擬手把
    'connect_xbox',
    'disconnect_xbox',
    'is_xbox_connected',
    'is_xbox_available',
    'set_xbox_sensitivity',
    'set_xbox_deadzone',
    'get_xbox_statistics',
    'send_mouse_click_xbox',
    
    # 滑鼠點擊
    'send_mouse_click',
    'send_mouse_click_sendinput',
    'send_mouse_click_hardware',
    'send_mouse_click_mouse_event',
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


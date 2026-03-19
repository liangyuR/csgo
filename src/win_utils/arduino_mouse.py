# arduino_mouse.py - Arduino Leonardo 滑鼠控制模組
"""
透過 Arduino Leonardo 的 USB HID 功能實現硬體級別的滑鼠移動。
Arduino Leonardo 可模擬原生 USB 滑鼠，非常隱蔽。
"""

import struct
import threading
import time
from typing import Optional

import serial
import serial.tools.list_ports


class ArduinoMouse:
    """Arduino Leonardo 滑鼠控制器

    使用 Arduino Leonardo 的 USB HID 功能模擬滑鼠移動。
    """

    def __init__(self):
        self._serial: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._connected = False
        self._com_port: str = ""
        self._baud_rate: int = 115200

    def connect(self, com_port: str, baud_rate: int = 115200) -> bool:
        """連線到 Arduino Leonardo

        Args:
            com_port: COM 埠 (例如 'COM7')
            baud_rate: 波特率，預設 115200

        Returns:
            是否成功連線
        """
        with self._lock:
            # 關閉舊連線
            if self._serial and self._serial.is_open:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._connected = False

            try:
                self._serial = serial.Serial(com_port, baud_rate, timeout=0.1)
                self._com_port = com_port
                self._baud_rate = baud_rate
                self._connected = True
                # 等待 Arduino 重啟（Leonardo 連線時會自動重啟）
                time.sleep(2)
                print(f"[Arduino] 成功連線到 {com_port}")
                return True
            except serial.SerialException as e:
                print(f"[Arduino] 連線失敗: {e}")
                self._connected = False
                return False
            except Exception as e:
                print(f"[Arduino] 連線時發生錯誤: {e}")
                self._connected = False
                return False

    def disconnect(self):
        """斷開連線"""
        with self._lock:
            if self._serial and self._serial.is_open:
                try:
                    self._serial.close()
                except Exception:
                    pass
            self._connected = False
            print("[Arduino] 已斷開連線")

    def is_connected(self) -> bool:
        """檢查是否已連線"""
        return self._connected and self._serial is not None and self._serial.is_open

    def move(self, dx: int, dy: int):
        """移動滑鼠

        Args:
            dx: X 方向移動量 (-128 ~ 127)
            dy: Y 方向移動量 (-128 ~ 127)
        """
        if not self.is_connected():
            return

        # 限制範圍在 -128 到 127 之間 (signed char)
        dx = max(-128, min(127, int(dx)))
        dy = max(-128, min(127, int(dy)))

        try:
            # struct.pack('bb') 代表打包成兩個 signed char (byte)
            data = struct.pack('bb', dx, dy)
            with self._lock:
                if self._serial and self._serial.is_open:
                    self._serial.write(data)
        except serial.SerialException:
            # 連線可能已斷開
            self._connected = False
        except Exception:
            pass

    @property
    def com_port(self) -> str:
        """當前連線的 COM 埠"""
        return self._com_port


# 全域單例
arduino_mouse = ArduinoMouse()


def send_mouse_move_arduino(dx: int, dy: int):
    """Arduino Leonardo 滑鼠移動（直接執行）"""
    arduino_mouse.move(dx, dy)


def get_available_com_ports() -> list[str]:
    """獲取可用的 COM 埠列表

    Returns:
        COM 埠名稱列表 (例如 ['COM1', 'COM3', 'COM7'])
    """
    ports = serial.tools.list_ports.comports()
    return [port.device for port in ports]


def connect_arduino(com_port: str, baud_rate: int = 115200) -> bool:
    """連線到 Arduino Leonardo

    Args:
        com_port: COM 埠 (例如 'COM7')
        baud_rate: 波特率，預設 115200

    Returns:
        是否成功連線
    """
    return arduino_mouse.connect(com_port, baud_rate)


def disconnect_arduino():
    """斷開 Arduino 連線"""
    arduino_mouse.disconnect()


def is_arduino_connected() -> bool:
    """檢查 Arduino 是否已連線"""
    return arduino_mouse.is_connected()

# status_panel.py
"""
Fluent Design 風格的狀態面板 (Redesigned)
使用 QLayout 和 QWidget 進行排版，提供更現代、整齊的視覺效果
支援 Windows Acrylic 毛玻璃效果
"""
import os
import sys
import ctypes
from ctypes import POINTER, pointer, sizeof, byref, WinDLL, c_int
from ctypes.wintypes import DWORD, ULONG
from PyQt6.QtWidgets import (QWidget, QApplication, QVBoxLayout, QHBoxLayout, 
                             QLabel, QFrame, QGraphicsDropShadowEffect, QSpacerItem, QSizePolicy)
from PyQt6.QtGui import (QPainter, QColor, QFont, QPixmap, QLinearGradient, 
                         QBrush, QPainterPath, QPen)
from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal

from core.language_manager import get_text, language_manager

# 嘗試導入 qfluentwidgets 的主題函數
try:
    from qfluentwidgets import isDarkTheme, themeColor
    HAS_FLUENT_WIDGETS = True
except ImportError:
    HAS_FLUENT_WIDGETS = False
    def isDarkTheme():
        return True  # 預設深色主題

# 導入主題顏色定義
try:
    from gui.fluent_app.theme_colors import ThemeColors, to_css_rgba
    HAS_THEME_COLORS = True
except ImportError:
    HAS_THEME_COLORS = False

# --- Win32 Acrylic 效果所需的結構體 ---
class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState",   DWORD),
        ("AccentFlags",   DWORD),
        ("GradientColor", DWORD),
        ("AnimationId",   DWORD),
    ]

class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute",   DWORD),
        ("Data",        POINTER(_ACCENT_POLICY)),
        ("SizeOfData",  ULONG),
    ]

class _MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth",    c_int),
        ("cxRightWidth",   c_int),
        ("cyTopHeight",    c_int),
        ("cyBottomHeight", c_int),
    ]

# 常量
_WCA_ACCENT_POLICY = 19
_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
_ACCENT_DISABLED = 0

# --- Fluent Design 顏色方案 ---
class FluentColors:
    """Fluent Design 配色方案 - 支持深色/淺色主題
    現已整合 ThemeColors 模組的統一顏色定義
    """
    
    @staticmethod
    def to_css_rgba(color: QColor) -> str:
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha() / 255.0})"

    @staticmethod
    def get_background_color():
        if HAS_THEME_COLORS:
            return ThemeColors.PANEL_BACKGROUND.qcolor()
        if isDarkTheme():
            return QColor(30, 30, 30, 255)  # 深色主題背景
        else:
            return QColor(255, 255, 255, 255)  # 亮色主題背景

    @staticmethod
    def get_text_primary_color():
        if HAS_THEME_COLORS:
            return ThemeColors.TEXT_PRIMARY.qcolor()
        return QColor(255, 255, 255) if isDarkTheme() else QColor(26, 26, 26)
        
    @staticmethod
    def get_text_secondary_color():
        if HAS_THEME_COLORS:
            return ThemeColors.TEXT_SECONDARY.qcolor()
        return QColor(160, 160, 160) if isDarkTheme() else QColor(90, 90, 90)

    @staticmethod
    def get_border_color():
        if HAS_THEME_COLORS:
            return ThemeColors.PANEL_BORDER.qcolor()
        return QColor(255, 255, 255, 20) if isDarkTheme() else QColor(0, 0, 0, 15)

    @staticmethod
    def get_accent_color():
        if HAS_THEME_COLORS:
            return ThemeColors.ACCENT.qcolor()
        return QColor(0, 122, 255)  # macOS Blue
    
    @staticmethod
    def get_success_color():
        if HAS_THEME_COLORS:
            return ThemeColors.SUCCESS.qcolor()
        return QColor(52, 199, 89) if not isDarkTheme() else QColor(50, 215, 75)
    
    @staticmethod
    def get_error_color():
        if HAS_THEME_COLORS:
            return ThemeColors.ERROR.qcolor()
        return QColor(255, 59, 48) if not isDarkTheme() else QColor(255, 69, 58)
         
    # 保持向後兼容的靜態屬性
    @property
    def SUCCESS(self):
        return self.get_success_color()
    
    @property
    def ERROR(self):
        return self.get_error_color()

# 創建全局實例用於屬性訪問
_fluent_colors_instance = FluentColors()
FluentColors.SUCCESS = _fluent_colors_instance.get_success_color()
FluentColors.ERROR = _fluent_colors_instance.get_error_color()

class StatusIndicator(QWidget):
    """一個簡單的圓點狀態指示器"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 10) # Slightly smaller
        self._active = False
        self._color = FluentColors.ERROR
        
    def set_status(self, active: bool):
        self._active = active
        self._color = FluentColors.SUCCESS if active else FluentColors.ERROR
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(self._color))
        painter.setPen(Qt.PenStyle.NoPen)
        # 畫在中間
        painter.drawEllipse(1, 1, 8, 8)

class StatusRow(QWidget):
    """通用狀態行 Widget"""
    def __init__(self, label_text, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 標籤
        self.label = QLabel(label_text, self)
        self.label.setObjectName("statusLabel")
        
        # 值 (可以是文字，也可以是 Widget)
        self.value_label = QLabel("", self)
        self.value_label.setObjectName("statusValue")
        
        # 彈性空間
        layout.addWidget(self.label)
        layout.addStretch()
        layout.addWidget(self.value_label)

    def set_value(self, text, color=None):
        self.value_label.setText(text)
        if color:
            self.value_label.setStyleSheet(f"color: {color};")
        else:
            # 重置為預設樣式
            pass

class StatusPanel(QWidget):
    """
    MacOS 風格的狀態面板 (Widget版)
    支援 Windows Acrylic 液態毛玻璃效果
    """
    # 都改成0 讓它自動適應
    PANEL_WIDTH = 0
    PANEL_HEIGHT = 0
    ACRYLIC_PANEL_WIDTH = 0
    ACRYLIC_PANEL_HEIGHT = 0
    BORDER_RADIUS = 24 # MacOS rounded corners

    def __init__(self, config):
        super().__init__()
        self.setObjectName("statusPanelRoot")
        self.config = config
        self._acrylic_enabled = False  # 追蹤 Acrylic 是否已成功啟用
        self._shadow_effect = None     # 追蹤陰影特效實例
        
        # --- 視窗基本設定 ---
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        # 預設啟用透明背景（acrylic 啟用時會關閉）
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        
        # --- 拖動變數 ---
        self._drag_pos = None
        self._is_dragging = False

        # --- 這部分是重點：初始化 UI 佈局 ---
        self._init_ui()

        # --- 定時器 ---
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_display)
        self.timer.start(500) # 0.5秒刷新一次狀態

        # --- 緩存狀態 ---
        self.last_theme_dark = isDarkTheme()
        self.last_aim_state = None
        self.last_model_path = None
        self.last_mouse_method = None
        self.last_language = None
        self._last_acrylic_enabled = None  # 追蹤 config 的 acrylic 開關
        self._last_acrylic_alpha = None    # 追蹤 acrylic 不透明度

        # 初次設置樣式
        self._apply_panel_size()
        self._update_style()
        self.update_display() # 立即刷新一次內容

    def _apply_panel_size(self):
        """依據當前模式套用面板尺寸"""
        if self._acrylic_enabled:
            self.setFixedSize(self.ACRYLIC_PANEL_WIDTH, self.ACRYLIC_PANEL_HEIGHT)
        else:
            self.setFixedSize(self.PANEL_WIDTH, self.PANEL_HEIGHT)

    def showEvent(self, event):
        """視窗顯示時套用 Acrylic 效果和圓角"""
        super().showEvent(event)
        # 延遲套用，確保 HWND 已完全建立
        QTimer.singleShot(150, self._applyAcrylicEffect)
        QTimer.singleShot(200, self._applyWindowRoundedCorners)

    def resizeEvent(self, event):
        """視窗大小改變時重新套用圓角 region (Win10 fallback)"""
        super().resizeEvent(event)
        self._applyWindowRoundedCorners()

    def _applyWindowRoundedCorners(self):
        """設定視窗圓角
        
        Win11: 使用 DWM DWMWA_WINDOW_CORNER_PREFERENCE
        Win10 fallback: 使用 CreateRoundRectRgn + SetWindowRgn 裁剪視窗
        """
        if sys.platform != 'win32':
            return
        try:
            hwnd = int(self.winId())
            if hwnd == 0:
                return
            dwmapi = WinDLL("dwmapi")
            
            # 嘗試 Win11 DWM 圓角設定
            try:
                DWMWA_WINDOW_CORNER_PREFERENCE = 33
                DWMWCP_DONOTROUND = c_int(1)
                DWMWCP_ROUND = c_int(2)  # 大圓角
                corner_pref = DWMWCP_ROUND if self._acrylic_enabled else DWMWCP_DONOTROUND
                dwmapi.DwmSetWindowAttribute(
                    hwnd, DWORD(DWMWA_WINDOW_CORNER_PREFERENCE),
                    byref(corner_pref), 4
                )
            except Exception:
                pass
            
            # 保險方案：使用 SetWindowRgn 裁剪圓角
            # 某些情況（例如 Tool 視窗）Win11 的 DWM 圓角不一定穩定生效
            gdi32 = WinDLL("gdi32")
            user32 = WinDLL("user32")
            w, h = self.width(), self.height()
            radius = self.BORDER_RADIUS
            rgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, radius, radius)
            user32.SetWindowRgn(hwnd, rgn, True)
        except Exception:
            pass

    def _applyAcrylicEffect(self):
        """應用 Windows Acrylic 液態毛玻璃效果到狀態面板
        
        關鍵技術點：
        1. WA_TranslucentBackground 會建立 Layered Window (WS_EX_LAYERED)，
           會繞過 DWM 合成，因此 Acrylic 無法作用。必須關閉。
        2. 必須呼叫 DwmExtendFrameIntoClientArea 將 DWM 玻璃框延伸至整個客戶區，
           這樣 SetWindowCompositionAttribute 的 Acrylic 效果才能在客戶區域渲染。
        3. paintEvent 中使用 CompositionMode_Source 填充透明色，
           讓 DWM 合成的 Acrylic 效果透出。
        """
        if sys.platform != 'win32':
            return

        enable = getattr(self.config, 'enable_acrylic', True)
        
        try:
            hwnd = int(self.winId())
            if hwnd == 0:
                return

            user32 = WinDLL("user32")
            dwmapi = WinDLL("dwmapi")

            accentPolicy = _ACCENT_POLICY()
            winCompAttrData = _WINCOMPATTRDATA()
            winCompAttrData.Attribute = _WCA_ACCENT_POLICY
            winCompAttrData.SizeOfData = sizeof(accentPolicy)
            winCompAttrData.Data = pointer(accentPolicy)

            if not enable:
                # 停用 Acrylic - 恢復到普通模式
                accentPolicy.AccentState = _ACCENT_DISABLED
                accentPolicy.GradientColor = 0
                accentPolicy.AccentFlags = 0
                accentPolicy.AnimationId = 0
                user32.SetWindowCompositionAttribute(hwnd, pointer(winCompAttrData))
                
                # 恢復 WA_TranslucentBackground 用於圓角透明
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                self._acrylic_enabled = False
                
                # 恢復陰影
                self._applyShadowEffect()
                self.main_layout.setContentsMargins(10, 10, 10, 10)
                self._apply_panel_size()
                self._update_style()
                self._applyWindowRoundedCorners()
                self.update()
                return

            # === 啟用 Acrylic ===
            
            # 步驟 1: 關閉 WA_TranslucentBackground
            # Layered window (WS_EX_LAYERED) 繞過 DWM，acrylic 無法生效
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            
            # 步驟 2: 將 DWM 玻璃框延伸到整個客戶區
            margins = _MARGINS(-1, -1, -1, -1)
            dwmapi.DwmExtendFrameIntoClientArea(hwnd, byref(margins))
            
            # 步驟 3: 嘗試設定 Win11 圓角 (DWMWA_WINDOW_CORNER_PREFERENCE = 33)
            try:
                DWMWA_WINDOW_CORNER_PREFERENCE = 33
                DWMWCP_ROUND = c_int(2)  # 圓角
                dwmapi.DwmSetWindowAttribute(
                    hwnd, DWORD(DWMWA_WINDOW_CORNER_PREFERENCE),
                    byref(DWMWCP_ROUND), sizeof(DWMWCP_ROUND)
                )
            except Exception:
                pass  # Win10 不支援，忽略

            # 步驟 4: 計算 gradientColor
            raw_alpha = getattr(self.config, 'acrylic_window_alpha', 187)
            alpha = max(0, min(255, int(raw_alpha)))
            alpha_hex = hex(alpha)[2:].upper().zfill(2)

            is_dark = isDarkTheme()
            if is_dark:
                gradient_str = f"1A1A1A{alpha_hex}"
            else:
                gradient_str = f"F5F5F5{alpha_hex}"

            # 轉換 RRGGBBAA -> AABBGGRR (Win32 byte order)
            gradient_reversed = ''.join(gradient_str[i:i+2] for i in range(6, -1, -2))
            gradient_color = DWORD(int(gradient_reversed, base=16))

            # 步驟 5: 套用 Acrylic Accent Policy
            accentPolicy.AccentState = _ACCENT_ENABLE_ACRYLICBLURBEHIND
            accentPolicy.GradientColor = gradient_color
            accentPolicy.AccentFlags = DWORD(0x20 | 0x40 | 0x80 | 0x100)  # 啟用陰影邊框
            accentPolicy.AnimationId = DWORD(0)

            user32.SetWindowCompositionAttribute(hwnd, pointer(winCompAttrData))
            self._acrylic_enabled = True
            
            # Acrylic 模式不需要 Qt 層面的陰影和邊距
            self._removeShadowEffect()
            self.main_layout.setContentsMargins(0, 0, 0, 0)
            self._apply_panel_size()
            self._update_style()
            self._applyWindowRoundedCorners()
            self.update()

        except Exception as e:
            print(f"[StatusPanel] 套用 Acrylic 效果失敗: {e}")
            self._acrylic_enabled = False
            # 失敗時恢復 WA_TranslucentBackground
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def _applyShadowEffect(self):
        """套用 Qt 陰影特效（非 Acrylic 模式使用）"""
        if self._shadow_effect is None:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(20)
            shadow.setColor(QColor(0, 0, 0, 60))
            shadow.setOffset(0, 4)
            self.container.setGraphicsEffect(shadow)
            self._shadow_effect = shadow

    def _removeShadowEffect(self):
        """移除 Qt 陰影特效（Acrylic 模式下 DWM 提供陰影）"""
        self.container.setGraphicsEffect(None)
        self._shadow_effect = None

    def paintEvent(self, event):
        """自訂繪製 - Acrylic 模式下清除背景讓 DWM 毛玻璃透出"""
        if self._acrylic_enabled:
            painter = QPainter(self)
            # CompositionMode_Source: 直接替換像素（不混合）
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)

            # 先清空整個區域，再僅填入圓角客戶區，避免 Acrylic 呈現方角
            painter.fillRect(self.rect(), QColor(0, 0, 0, 0))

            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            path = QPainterPath()
            rect = self.rect().adjusted(0, 0, -1, -1)
            path.addRoundedRect(float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()),
                                float(self.BORDER_RADIUS), float(self.BORDER_RADIUS))

            # 使用 alpha=1 而非 alpha=0：
            # alpha=0 可能讓 DWM 將區域視為玻璃框，拖動事件被攔截
            painter.fillPath(path, QColor(0, 0, 0, 1))
            painter.end()
        else:
            # 非 Acrylic 模式：使用預設繪製（WA_TranslucentBackground 處理透明）
            super().paintEvent(event)

    def _init_ui(self):
        """初始化 UI 結構"""
        # 主 Layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10) # Space for shadow

        # 背景容器 (QFrame)，負責圓角和背景色
        self.container = QFrame(self)
        self.container.setObjectName("container")
        
        # Shadow Effect（預設啟用，Acrylic 啟用時會移除）
        self._applyShadowEffect()

        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(16, 14, 16, 14)
        self.container_layout.setSpacing(6) # Tighter vertical spacing

        # 1. 標題列
        self.header_layout = QHBoxLayout()
        self.header_layout.setSpacing(12)
        
        # Logo PlaceHolder (用來佔位，保持排版不亂)
        self.logo_placeholder = QLabel()
        self.logo_placeholder.setFixedSize(20, 20)
        self.header_layout.addWidget(self.logo_placeholder)

        # 真正的 Logo (浮動顯示，尺寸較大)
        self.logo_label = QLabel(self.container)
        self.logo_label.setFixedSize(32, 32)
        self.logo_label.setScaledContents(True)
        # 手動定位：讓它重疊在左上角 (根據 layout margins 計算)
        # container margins: 16 (left), 14 (top)
        # placeholder 30x40，logo 40x40
        # 水平：讓 logo 左邊超出 placeholder 一些 → x=6
        # 垂直：與 placeholder 頂部對齊 → y=14，使文字垂直居中於 logo
        self.logo_label.move(10, 10)
        self.logo_label.raise_()

        # Title Group (垂直排列 Title 和 Version，或者水平) -> 採用水平
        self.title_label = QLabel("Axiom")
        self.title_label.setObjectName("titleLabel")
        
        self.version_label = QLabel("v6.0")
        self.version_label.setObjectName("versionLabel")

        # self.header_layout.addWidget(self.logo_label) # 移除原本的添加
        self.header_layout.addWidget(self.title_label)
        self.header_layout.addWidget(self.version_label)
        self.header_layout.addStretch()

        # 2. 分隔線 (用 QFrame 模擬)
        self.separator = QFrame()
        self.separator.setFrameShape(QFrame.Shape.HLine)
        self.separator.setFrameShadow(QFrame.Shadow.Plain)
        self.separator.setFixedHeight(1)
        self.separator.setObjectName("separator")

        # 3. 狀態行 - 自動瞄準
        self.aim_row = QWidget()
        self.aim_layout = QHBoxLayout(self.aim_row)
        self.aim_layout.setContentsMargins(0, 0, 0, 0)
        self.aim_layout.setSpacing(8)
        
        self.aim_indicator = StatusIndicator()
        self.aim_text_label = QLabel(get_text('auto_aim'))
        self.aim_text_label.setObjectName("statusLabel")
        self.aim_status_label = QLabel()
        self.aim_status_label.setObjectName("statusValue")

        self.aim_layout.addWidget(self.aim_indicator)
        self.aim_layout.addWidget(self.aim_text_label)
        self.aim_layout.addStretch()
        self.aim_layout.addWidget(self.aim_status_label)

        # 4. 狀態行 - 目前模型
        self.model_row = StatusRow(get_text('status_panel_current_model'))

        # 5. 狀態行 - 目前目標類別
        self.target_row = StatusRow(get_text('active_target_class'))

        # 6. 狀態行 - 滑鼠移動
        self.mouse_row = StatusRow(get_text('mouse_move_method'))

        # 加入容器
        self.container_layout.addLayout(self.header_layout)
        self.container_layout.addWidget(self.separator)
        self.container_layout.addSpacing(2) 
        self.container_layout.addWidget(self.aim_row)
        self.container_layout.addWidget(self.model_row)
        self.container_layout.addWidget(self.target_row)
        self.container_layout.addWidget(self.mouse_row)
        self.container_layout.addStretch()

        self.main_layout.addWidget(self.container)

        self._load_logo()

    def _load_logo(self):
        """載入 Logo"""
        logo_path = os.path.join(os.path.dirname(__file__), 'logo.png')
        
        if os.path.exists(logo_path):
            self.logo_label.setPixmap(QPixmap(logo_path))
        else:
            self.logo_label.clear()

    def _update_style(self):
        """更新 QSS 樣式表"""
        text_primary = FluentColors.to_css_rgba(FluentColors.get_text_primary_color())
        text_secondary = FluentColors.to_css_rgba(FluentColors.get_text_secondary_color())
        border_color = FluentColors.to_css_rgba(FluentColors.get_border_color())
        
        # 根據 Acrylic 是否啟用決定容器背景
        if self._acrylic_enabled:
            # Acrylic 啟用時：容器背景設為透明，讓 DWM 層的毛玻璃效果透出
            # 不需要圓角（DWM 會處理 Win11 圓角，Win10 為矩形即可）
            container_bg = "transparent"
            container_border = "none"
            container_radius = 0
        else:
            # Acrylic 停用時：使用不透明背景 + 圓角
            bg_color_obj = FluentColors.get_background_color()
            container_bg = FluentColors.to_css_rgba(bg_color_obj)
            container_border = f"1px solid {border_color}"
            container_radius = self.BORDER_RADIUS
        
        style_sheet = f"""
            QWidget#statusPanelRoot {{
                background: transparent;
                border: none;
            }}
            QFrame#container {{
                background-color: {container_bg};
                border: {container_border};
                border-radius: {container_radius}px;
            }}
            QLabel#titleLabel {{
                color: {text_primary};
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                font-size: 18px;
                font-weight: 700;
                background: transparent;
            }}
            QLabel#versionLabel {{
                color: {text_secondary};
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                font-size: 14px;
                padding-top: 3px;
                background: transparent;
            }}
            QLabel#statusLabel {{
                color: {text_secondary};
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                font-size: 12px;
                background: transparent;
            }}
            QLabel#statusValue {{
                color: {text_primary};
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                font-size: 12px;
                font-weight: 500;
                background: transparent;
            }}
            QFrame#separator {{
                color: {border_color}; 
                background-color: {border_color}; 
                border: none;
            }}
        """
        self.setStyleSheet(style_sheet)

    def update_display(self):
        """更新顯示數據和主題檢測"""
        
        # 1. 檢查是否顯示
        show_panel = getattr(self.config, 'show_status_panel', True)
        if not show_panel:
            if self.isVisible(): self.hide()
            return
        elif not self.isVisible():
            self.show()

        # 2. 檢查主題變化 (簡單輪詢)
        current_theme_dark = isDarkTheme()
        if current_theme_dark != self.last_theme_dark:
            self.last_theme_dark = current_theme_dark
            self._update_style()
            self._load_logo()
            # 主題變化時重新套用 Acrylic（更新毛玻璃顏色）
            self._applyAcrylicEffect()

        # 2.5 檢查 Acrylic 開關或不透明度變化
        current_acrylic = getattr(self.config, 'enable_acrylic', True)
        current_alpha = getattr(self.config, 'acrylic_window_alpha', 187)
        acrylic_changed = (current_acrylic != self._last_acrylic_enabled or
                           current_alpha != self._last_acrylic_alpha)
        if acrylic_changed:
            self._last_acrylic_enabled = current_acrylic
            self._last_acrylic_alpha = current_alpha
            self._applyAcrylicEffect()

        # 3. 獲取數據
        current_aim = self.config.AimToggle
        current_model = getattr(self.config, 'model_path', '')
        current_target_class = getattr(self.config, 'active_target_class', '')
        current_method = getattr(self.config, 'mouse_move_method', 'ddxoft')
        current_lang = language_manager.get_current_language()

        # 檢查是否需要更新 UI 文本 (例如語言改變或狀態改變)
        # 為了簡化，簡單比較關鍵值，或者直接更新所有文字(開銷很小)
        
        # 更新 Auto Aim
        if current_aim:
            self.aim_status_label.setText(get_text("status_panel_on"))
            self.aim_status_label.setStyleSheet(f"color: {FluentColors.to_css_rgba(FluentColors.SUCCESS)};")
            self.aim_indicator.set_status(True)
        else:
            self.aim_status_label.setText(get_text("status_panel_off"))
            self.aim_status_label.setStyleSheet(f"color: {FluentColors.to_css_rgba(FluentColors.ERROR)};")
            self.aim_indicator.set_status(False)
        self.aim_text_label.setText(get_text('auto_aim'))

        # 更新 Model
        from core.model_registry import get_model_spec

        model_spec = get_model_spec(getattr(self.config, 'model_id', ''))
        model_name = model_spec.display_name if model_spec else (os.path.basename(current_model) if current_model else "None")
        if len(model_name) > 25: model_name = model_name[:22] + "..."
        self.model_row.label.setText(get_text('status_panel_current_model'))
        self.model_row.set_value(model_name)

        self.target_row.label.setText(get_text('active_target_class'))
        self.target_row.set_value(str(current_target_class).upper())

        # 更新 Mouse Method
        mouse_map = {'sendinput': 'SendInput', 'mouse_event': 'mouse_event', 'ddxoft': 'ddxoft', 'xbox': 'Xbox 360'}
        disp_method = mouse_map.get(current_method, str(current_method))
        
        # DDXoft check
        method_color = None
        if current_method == 'ddxoft':
            try:
                from win_utils import ddxoft_mouse
                if ddxoft_mouse.is_available():
                    disp_method += " ✓"
                    method_color = FluentColors.to_css_rgba(FluentColors.SUCCESS)
                else:
                    disp_method += " ✗"
                    method_color = FluentColors.to_css_rgba(FluentColors.ERROR)
            except ImportError:
                 pass
        elif current_method == 'xbox':
            try:
                from win_utils import is_xbox_connected
                if is_xbox_connected():
                    disp_method += " ✓"
                    method_color = FluentColors.to_css_rgba(FluentColors.SUCCESS)
                else:
                    disp_method += " ✗"
                    method_color = FluentColors.to_css_rgba(FluentColors.ERROR)
            except ImportError:
                disp_method += " ✗"
                method_color = FluentColors.to_css_rgba(FluentColors.ERROR)
        
        self.mouse_row.label.setText(get_text('mouse_move_method'))
        self.mouse_row.set_value(disp_method, method_color)

    # --- 拖動邏輯 ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._is_dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._is_dragging and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._drag_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()

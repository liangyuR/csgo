"""Overlay for FOV and detections."""

from __future__ import annotations

import ctypes
import queue
from typing import TYPE_CHECKING, List

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

try:
    from gui.fluent_app.theme_colors import ThemeColors

    HAS_THEME_COLORS = True
except ImportError:
    HAS_THEME_COLORS = False

if TYPE_CHECKING:
    from core.config import Config
    from core.detection_state import DetectionPayload
    from core.model_registry import ModelSpec


class OverlayColors:
    @staticmethod
    def get_fov_color() -> QColor:
        return ThemeColors.OVERLAY_FOV.qcolor() if HAS_THEME_COLORS else QColor(255, 0, 0, 180)

    @staticmethod
    def get_box_color() -> QColor:
        return ThemeColors.OVERLAY_BOX.qcolor() if HAS_THEME_COLORS else QColor(0, 255, 0, 200)

    @staticmethod
    def get_confidence_text_color() -> QColor:
        return ThemeColors.OVERLAY_CONFIDENCE_TEXT.qcolor() if HAS_THEME_COLORS else QColor(255, 255, 0, 220)

    @staticmethod
    def get_detect_range_color() -> QColor:
        return ThemeColors.OVERLAY_DETECT_RANGE.qcolor() if HAS_THEME_COLORS else QColor(0, 140, 255, 90)

    @staticmethod
    def get_tracker_line_color() -> QColor:
        return ThemeColors.OVERLAY_TRACKER_LINE.qcolor() if HAS_THEME_COLORS else QColor(255, 255, 255, 50)

    @staticmethod
    def get_tracker_current_color() -> QColor:
        return ThemeColors.OVERLAY_TRACKER_CURRENT.qcolor() if HAS_THEME_COLORS else QColor(0, 255, 255, 60)

    @staticmethod
    def get_tracker_predicted_color() -> QColor:
        return ThemeColors.OVERLAY_TRACKER_PREDICTED.qcolor() if HAS_THEME_COLORS else QColor(255, 0, 255, 80)


class PyQtOverlay(QWidget):
    def __init__(self, payload_queue, config):
        super().__init__()
        self.payload_queue = payload_queue
        self.config = config
        self.boxes: List[List[float]] = []
        self.confidences: List[float] = []
        self.class_ids: List[int] = []

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(0, 0, config.width, config.height)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_overlay)
        self._last_timer_interval_ms = max(int(config.detect_interval * 1000), 16)
        self.timer.start(self._last_timer_interval_ms)
        self.show()
        self.set_click_through()

    def set_click_through(self):
        try:
            hwnd = self.winId().__int__()
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x80000
            WS_EX_TRANSPARENT = 0x20
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception as e:
            print(f"Mouse click-through setup failed: {e}")

    def update_overlay(self) -> None:
        desired_interval = max(int(self.config.detect_interval * 1000), 16)
        if desired_interval != self._last_timer_interval_ms:
            self.timer.setInterval(desired_interval)
            self._last_timer_interval_ms = desired_interval

        try:
            payload = self.payload_queue.get_nowait()
        except queue.Empty:
            payload = None

        if payload is not None:
            self.boxes = payload.boxes.tolist()
            self.confidences = payload.confidences.tolist()
            self.class_ids = payload.class_ids.tolist()

        if self.config.AimToggle:
            self.update()

    def _model_labels(self) -> List[str]:
        from core.model_registry import get_model_spec

        spec = get_model_spec(getattr(self.config, "model_id", ""))
        return spec.labels if spec else []

    def draw_corner_box(self, painter, x1, y1, x2, y2):
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        box_size = min(width, height)
        point_size = max(1, min(36, int(box_size * 0.08)))
        painter.drawEllipse(x1 - point_size // 2, y1 - point_size // 2, point_size, point_size)
        painter.drawEllipse(x2 - point_size // 2, y1 - point_size // 2, point_size, point_size)
        painter.drawEllipse(x1 - point_size // 2, y2 - point_size // 2, point_size, point_size)
        painter.drawEllipse(x2 - point_size // 2, y2 - point_size // 2, point_size, point_size)

    def draw_fov_corners(self, painter, cx, cy, fov, corner_length=20):
        x1 = cx - fov // 2
        y1 = cy - fov // 2
        x2 = cx + fov // 2
        y2 = cy + fov // 2
        painter.drawLine(x1, y1, x1 + corner_length, y1)
        painter.drawLine(x1, y1, x1, y1 + corner_length)
        painter.drawLine(x2, y1, x2 - corner_length, y1)
        painter.drawLine(x2, y1, x2, y1 + corner_length)
        painter.drawLine(x1, y2, x1 + corner_length, y2)
        painter.drawLine(x1, y2, x1, y2 - corner_length)
        painter.drawLine(x2, y2, x2 - corner_length, y2)
        painter.drawLine(x2, y2, x2, y2 - corner_length)

    def draw_tracker_prediction(self, painter):
        if not getattr(self.config, "tracker_enabled", False):
            return
        if not getattr(self.config, "tracker_show_prediction", True):
            return
        if not getattr(self.config, "tracker_has_prediction", False):
            return

        cx = int(getattr(self.config, "tracker_current_x", 0))
        cy = int(getattr(self.config, "tracker_current_y", 0))
        px = int(getattr(self.config, "tracker_predicted_x", 0))
        py = int(getattr(self.config, "tracker_predicted_y", 0))
        if cx == 0 and cy == 0:
            return

        painter.setPen(QPen(OverlayColors.get_tracker_line_color(), 1, Qt.PenStyle.DotLine))
        painter.drawLine(cx, cy, px, py)

        current_color = OverlayColors.get_tracker_current_color()
        painter.setPen(QPen(current_color, 2))
        painter.setBrush(QColor(current_color.red(), current_color.green(), current_color.blue(), current_color.alpha() // 2))
        painter.drawEllipse(cx - 2, cy - 2, 4, 4)

        predicted_color = OverlayColors.get_tracker_predicted_color()
        painter.setPen(QPen(predicted_color, 2))
        painter.setBrush(QColor(predicted_color.red(), predicted_color.green(), predicted_color.blue(), predicted_color.alpha() // 2))
        painter.drawEllipse(px - 3, py - 3, 6, 6)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def paintEvent(self, event):
        if not self.config.AimToggle:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if getattr(self.config, "show_detect_range", False):
            painter.setPen(QPen(OverlayColors.get_detect_range_color(), 1))
            painter.drawRect(
                int(getattr(self.config, "capture_left", 0)),
                int(getattr(self.config, "capture_top", 0)),
                int(getattr(self.config, "capture_width", getattr(self.config, "detect_range_size", self.config.height))),
                int(getattr(self.config, "capture_height", getattr(self.config, "detect_range_size", self.config.height))),
            )

        if getattr(self.config, "show_fov", True):
            painter.setPen(QPen(OverlayColors.get_fov_color(), 2))
            self.draw_fov_corners(painter, self.config.crosshairX, self.config.crosshairY, self.config.fov_size)

        if getattr(self.config, "show_boxes", True) and len(self.boxes) > 0:
            labels = self._model_labels()
            pen_box = QPen(OverlayColors.get_box_color(), 2)
            pen_text = QPen(OverlayColors.get_confidence_text_color(), 1)
            painter.setPen(pen_box)
            painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))

            for i, box in enumerate(self.boxes):
                x1, y1, x2, y2 = map(int, box)
                self.draw_corner_box(painter, x1, y1, x2, y2)

                if i < len(self.confidences):
                    confidence = self.confidences[i]
                    label = labels[self.class_ids[i]] if i < len(self.class_ids) and self.class_ids[i] < len(labels) else ""
                    painter.setPen(pen_text)
                    painter.drawText(x1 - 20, y1 - 15, f"{label} {confidence:.0%}".strip())
                    painter.setPen(pen_box)

        self.draw_tracker_prediction(painter)

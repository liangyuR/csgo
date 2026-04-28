"""Small native PyQt6 widgets shared by the lightweight settings UI."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def tr(key: str, default: str | None = None) -> str:
    """Return translated text when available, otherwise a readable fallback."""
    fallback = default if default is not None else key.replace("_", " ").title()
    try:
        from core.language_manager import get_text

        text = get_text(key, fallback)
        return text or fallback
    except Exception:
        return fallback


def make_card(title: str, parent: QWidget | None = None) -> QFrame:
    card = QFrame(parent)
    card.setObjectName("settingsCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)

    title_label = QLabel(title, card)
    title_label.setObjectName("groupTitle")
    layout.addWidget(title_label)
    return card


def add_row(container: QFrame, label: str, widget: QWidget, description: str = "") -> None:
    layout = container.layout()
    if not isinstance(layout, QVBoxLayout):
        return

    row = QWidget(container)
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(12)

    text_box = QWidget(row)
    text_layout = QVBoxLayout(text_box)
    text_layout.setContentsMargins(0, 0, 0, 0)
    text_layout.setSpacing(2)

    label_widget = QLabel(label, text_box)
    label_widget.setObjectName("rowLabel")
    text_layout.addWidget(label_widget)
    if description:
        desc_widget = QLabel(description, text_box)
        desc_widget.setObjectName("rowDescription")
        desc_widget.setWordWrap(True)
        text_layout.addWidget(desc_widget)

    row_layout.addWidget(text_box, 1)
    row_layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)
    layout.addWidget(row)


class IntSliderSpin(QWidget):
    valueChanged = pyqtSignal(int)

    def __init__(
        self,
        minimum: int,
        maximum: int,
        suffix: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._suffix = suffix
        self._updating = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setMinimumWidth(170)
        self.slider.setRange(minimum, maximum)

        self.spin = QSpinBox(self)
        self.spin.setRange(minimum, maximum)
        self.spin.setSuffix(suffix)
        self.spin.setMinimumWidth(92)

        layout.addWidget(self.slider)
        layout.addWidget(self.spin)

        self.slider.valueChanged.connect(self._on_slider)
        self.spin.valueChanged.connect(self._on_spin)

    def setRange(self, minimum: int, maximum: int) -> None:
        self.slider.setRange(minimum, maximum)
        self.spin.setRange(minimum, maximum)

    def setControlsEnabled(self, enabled: bool) -> None:
        self.slider.setEnabled(enabled)
        self.spin.setEnabled(enabled)

    def setValue(self, value: int) -> None:
        value = max(self.spin.minimum(), min(self.spin.maximum(), int(value)))
        self._updating = True
        self.slider.setValue(value)
        self.spin.setValue(value)
        self._updating = False

    def value(self) -> int:
        return self.spin.value()

    def _on_slider(self, value: int) -> None:
        if self._updating:
            return
        self._updating = True
        self.spin.setValue(value)
        self._updating = False
        self.valueChanged.emit(value)

    def _on_spin(self, value: int) -> None:
        if self._updating:
            return
        self._updating = True
        self.slider.setValue(value)
        self._updating = False
        self.valueChanged.emit(value)


class FloatSpin(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(
        self,
        minimum: float,
        maximum: float,
        decimals: int = 2,
        step: float = 0.01,
        suffix: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.spin = QDoubleSpinBox(self)
        self.spin.setRange(minimum, maximum)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setMinimumWidth(110)
        self.spin.valueChanged.connect(self.valueChanged.emit)
        layout.addWidget(self.spin)

    def setValue(self, value: float) -> None:
        self.spin.setValue(float(value))

    def value(self) -> float:
        return self.spin.value()


VK_NAMES = {
    0x00: "None",
    0x01: "Mouse Left",
    0x02: "Mouse Right",
    0x04: "Mouse Middle",
    0x05: "Mouse X1",
    0x06: "Mouse X2",
    0x08: "Backspace",
    0x09: "Tab",
    0x0D: "Enter",
    0x10: "Shift",
    0x11: "Ctrl",
    0x12: "Alt",
    0x14: "CapsLock",
    0x1B: "Esc",
    0x20: "Space",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
    0x2D: "Insert",
    0x2E: "Delete",
}


def vk_to_name(vk_code: int) -> str:
    if vk_code in VK_NAMES:
        return VK_NAMES[vk_code]
    if 0x30 <= vk_code <= 0x39 or 0x41 <= vk_code <= 0x5A:
        return chr(vk_code)
    if 0x70 <= vk_code <= 0x7B:
        return f"F{vk_code - 0x70 + 1}"
    return f"0x{vk_code:02X}"


class KeyBindButton(QPushButton):
    keyBound = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vk_code = 0
        self._listening = False
        self.setMinimumWidth(130)
        self.clicked.connect(self._start_listening)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._update_text()

    def setVkCode(self, vk_code: int) -> None:
        self._vk_code = int(vk_code or 0)
        self._update_text()

    def vkCode(self) -> int:
        return self._vk_code

    def refreshText(self) -> None:
        if not self._listening:
            self._update_text()

    def _update_text(self) -> None:
        self.setText(vk_to_name(self._vk_code))

    def _start_listening(self) -> None:
        self._listening = True
        self.setText("Press key...")
        self.setFocus(Qt.FocusReason.MouseFocusReason)

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        clear_action = QAction("Clear", self)
        clear_action.triggered.connect(self._clear_binding)
        menu.addAction(clear_action)
        menu.exec(self.mapToGlobal(pos))

    def _clear_binding(self) -> None:
        self._vk_code = 0
        self._listening = False
        self._update_text()
        self.keyBound.emit(0)

    def keyPressEvent(self, event) -> None:
        if not self._listening:
            super().keyPressEvent(event)
            return

        vk = self._qt_key_to_vk(event.key())
        if vk:
            self._vk_code = vk
            self._update_text()
            self.keyBound.emit(vk)
        self._listening = False

    def mousePressEvent(self, event) -> None:
        if not self._listening:
            super().mousePressEvent(event)
            return

        mapping = {
            Qt.MouseButton.LeftButton: 0x01,
            Qt.MouseButton.RightButton: 0x02,
            Qt.MouseButton.MiddleButton: 0x04,
            Qt.MouseButton.XButton1: 0x05,
            Qt.MouseButton.XButton2: 0x06,
        }
        vk = mapping.get(event.button(), 0)
        if vk:
            self._vk_code = vk
            self._update_text()
            self.keyBound.emit(vk)
        self._listening = False

    def _qt_key_to_vk(self, qt_key: int) -> int:
        if Qt.Key.Key_A.value <= qt_key <= Qt.Key.Key_Z.value:
            return 0x41 + (qt_key - Qt.Key.Key_A.value)
        if Qt.Key.Key_0.value <= qt_key <= Qt.Key.Key_9.value:
            return 0x30 + (qt_key - Qt.Key.Key_0.value)
        if Qt.Key.Key_F1.value <= qt_key <= Qt.Key.Key_F12.value:
            return 0x70 + (qt_key - Qt.Key.Key_F1.value)

        mapping = {
            Qt.Key.Key_Escape: 0x1B,
            Qt.Key.Key_Tab: 0x09,
            Qt.Key.Key_Backspace: 0x08,
            Qt.Key.Key_Return: 0x0D,
            Qt.Key.Key_Enter: 0x0D,
            Qt.Key.Key_Insert: 0x2D,
            Qt.Key.Key_Delete: 0x2E,
            Qt.Key.Key_Space: 0x20,
            Qt.Key.Key_Left: 0x25,
            Qt.Key.Key_Up: 0x26,
            Qt.Key.Key_Right: 0x27,
            Qt.Key.Key_Down: 0x28,
            Qt.Key.Key_Shift: 0x10,
            Qt.Key.Key_Control: 0x11,
            Qt.Key.Key_Alt: 0x12,
            Qt.Key.Key_CapsLock: 0x14,
        }
        return mapping.get(qt_key, 0)


class SettingsPage(QWidget):
    """Scrollable settings page with simple card groups."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loading = False

        from PyQt6.QtWidgets import QScrollArea

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.content = QWidget(self.scroll)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(24, 22, 24, 22)
        self.content_layout.setSpacing(14)

        title_label = QLabel(title, self.content)
        title_label.setObjectName("pageTitle")
        self.content_layout.addWidget(title_label)

        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll)

    def add_card(self, title: str) -> QFrame:
        card = make_card(title, self.content)
        self.content_layout.addWidget(card)
        return card

    def finish(self) -> None:
        self.content_layout.addStretch(1)


def open_path(path: str) -> None:
    import os

    if hasattr(os, "startfile"):
        os.startfile(path)  # type: ignore[attr-defined]


def connect_if(widget: QWidget, signal_name: str, callback: Callable) -> None:
    signal = getattr(widget, signal_name, None)
    if signal is not None:
        signal.connect(callback)

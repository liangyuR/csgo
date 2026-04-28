"""Native PyQt6 settings window."""

from __future__ import annotations

import math
import os
import sys
import threading
from ctypes import WinDLL, byref, c_int
from ctypes.wintypes import DWORD

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)

from core.config import apply_model_constraints, bump_runtime_refresh_token, save_config
from core.model_registry import get_model_spec, is_cs2_model, list_model_specs
from version import __version__

from .widgets import (
    FloatSpin,
    IntSliderSpin,
    KeyBindButton,
    SettingsPage,
    add_row,
    open_path,
)


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")


def _is_dark(config) -> bool:
    return bool(getattr(config, "dark_mode", False))


class VisualsPage(SettingsPage):
    def __init__(self, parent=None) -> None:
        super().__init__("Display", parent)
        self._config = None

        display = self.add_card("Overlay")
        self.show_fov = QCheckBox("Show FOV")
        self.show_boxes = QCheckBox("Show boxes")
        self.show_confidence = QCheckBox("Show confidence")
        self.show_status = QCheckBox("Show status panel")
        self.show_detect_range = QCheckBox("Show detect range")
        for widget in (
            self.show_fov,
            self.show_boxes,
            self.show_confidence,
            self.show_status,
            self.show_detect_range,
        ):
            add_row(display, widget.text(), widget)

        appearance = self.add_card("Appearance")
        self.dark_mode = QCheckBox("Dark mode")
        self.enable_acrylic = QCheckBox("Enable acrylic")
        self.window_alpha = IntSliderSpin(0, 255)
        add_row(appearance, "Dark mode", self.dark_mode)
        add_row(appearance, "Enable acrylic", self.enable_acrylic)
        add_row(appearance, "Acrylic window alpha", self.window_alpha)
        self.finish()

        self.show_fov.toggled.connect(lambda v: self._set("show_fov", v))
        self.show_boxes.toggled.connect(lambda v: self._set("show_boxes", v))
        self.show_confidence.toggled.connect(lambda v: self._set("show_confidence", v))
        self.show_status.toggled.connect(lambda v: self._set("show_status_panel", v))
        self.show_detect_range.toggled.connect(lambda v: self._set("show_detect_range", v))
        self.dark_mode.toggled.connect(self._on_dark_mode)
        self.enable_acrylic.toggled.connect(self._on_acrylic)
        self.window_alpha.valueChanged.connect(self._on_alpha)

    def setConfig(self, config) -> None:
        self._config = config
        self._loading = True
        self.show_fov.setChecked(config.show_fov)
        self.show_boxes.setChecked(config.show_boxes)
        self.show_confidence.setChecked(config.show_confidence)
        self.show_status.setChecked(config.show_status_panel)
        self.show_detect_range.setChecked(config.show_detect_range)
        self.dark_mode.setChecked(bool(getattr(config, "dark_mode", False)))
        self.enable_acrylic.setChecked(bool(getattr(config, "enable_acrylic", True)))
        self.window_alpha.setValue(int(getattr(config, "acrylic_window_alpha", 187)))
        self._loading = False

    def _set(self, attr: str, value: bool) -> None:
        if self._config is not None and not self._loading:
            setattr(self._config, attr, bool(value))

    def _on_dark_mode(self, checked: bool) -> None:
        self._set("dark_mode", checked)
        window = self.window()
        if hasattr(window, "_applyThemeStyles"):
            window._applyThemeStyles()

    def _on_acrylic(self, checked: bool) -> None:
        self._set("enable_acrylic", checked)

    def _on_alpha(self, value: int) -> None:
        if self._config is not None and not self._loading:
            self._config.acrylic_window_alpha = int(value)


class AimPage(SettingsPage):
    def __init__(self, parent=None) -> None:
        super().__init__("Aim", parent)
        self._config = None
        self._model_specs = []

        model = self.add_card("Model")
        self.model_combo = QComboBox()
        self.class_combo = QComboBox()
        self.open_model_btn = QPushButton("Open Model Folder")
        add_row(model, "Model", self.model_combo)
        add_row(model, "Active target class", self.class_combo)
        add_row(model, "Model folder", self.open_model_btn)

        fov = self.add_card("FOV and detection")
        self.fov_size = IntSliderSpin(50, 500, " px")
        self.fov_follow = QCheckBox("Follow mouse")
        self.detect_range = IntSliderSpin(50, 1080, " px")
        add_row(fov, "FOV size", self.fov_size)
        add_row(fov, "FOV follows mouse", self.fov_follow)
        add_row(fov, "Detect range size", self.detect_range)

        general = self.add_card("General")
        self.detect_interval = IntSliderSpin(1, 100, " ms")
        self.confidence = IntSliderSpin(1, 100, "%")
        self.aim_part = QComboBox()
        self.aim_part.addItems(["head", "body", "both"])
        self.mouse_method = QComboBox()
        self.mouse_method.addItems(["ddxoft", "mouse_event", "arduino", "xbox"])
        self.always_aim = QCheckBox()
        self.keep_detecting = QCheckBox()
        self.sticky_target = QCheckBox()
        self.aim_deadzone = IntSliderSpin(0, 20, " px")
        self.lock_radius = IntSliderSpin(8, 300, " px")
        self.lock_time = IntSliderSpin(0, 500, " ms")
        add_row(general, "Detect interval", self.detect_interval)
        add_row(general, "Minimum confidence", self.confidence)
        add_row(general, "Aim part", self.aim_part)
        add_row(general, "Mouse move method", self.mouse_method)
        add_row(general, "Always aim", self.always_aim)
        add_row(general, "Keep detecting", self.keep_detecting)
        add_row(general, "Sticky target", self.sticky_target)
        add_row(general, "Aim deadzone", self.aim_deadzone)
        add_row(general, "Lock retain radius", self.lock_radius)
        add_row(general, "Lock retain time", self.lock_time)

        self.arduino_group = self.add_card("Arduino")
        self.com_combo = QComboBox()
        self.refresh_com_btn = QPushButton("Refresh")
        com_box = QWidget()
        com_layout = QHBoxLayout(com_box)
        com_layout.setContentsMargins(0, 0, 0, 0)
        com_layout.addWidget(self.com_combo)
        com_layout.addWidget(self.refresh_com_btn)
        self.arduino_status = QLabel("Disconnected")
        self.arduino_connect_btn = QPushButton("Connect")
        self.arduino_guide_btn = QPushButton("Open guide")
        self.arduino_spoof_btn = QPushButton("Spoof device")
        self.arduino_verify_btn = QPushButton("Verify spoof")
        self.arduino_test_btn = QPushButton("Test heart")
        add_row(self.arduino_group, "COM port", com_box)
        add_row(self.arduino_group, "Connection", self.arduino_status)
        add_row(self.arduino_group, "Connect", self.arduino_connect_btn)
        add_row(self.arduino_group, "Guide", self.arduino_guide_btn)
        add_row(self.arduino_group, "Spoof device", self.arduino_spoof_btn)
        add_row(self.arduino_group, "Verify spoof", self.arduino_verify_btn)
        add_row(self.arduino_group, "Test movement", self.arduino_test_btn)

        self.xbox_group = self.add_card("Xbox 360 Controller")
        self.xbox_sensitivity = IntSliderSpin(10, 500, "%")
        self.xbox_deadzone = IntSliderSpin(0, 50, "%")
        self.xbox_status = QLabel("Disconnected")
        self.xbox_connect_btn = QPushButton("Connect")
        add_row(self.xbox_group, "Sensitivity", self.xbox_sensitivity)
        add_row(self.xbox_group, "Deadzone", self.xbox_deadzone)
        add_row(self.xbox_group, "Connection", self.xbox_status)
        add_row(self.xbox_group, "Connect", self.xbox_connect_btn)

        pid = self.add_card("PID")
        self.pid_tabs = QTabWidget()
        self.pid_px = IntSliderSpin(0, 100)
        self.pid_ix = IntSliderSpin(0, 100)
        self.pid_dx = IntSliderSpin(0, 100)
        self.pid_py = IntSliderSpin(0, 100)
        self.pid_iy = IntSliderSpin(0, 100)
        self.pid_dy = IntSliderSpin(0, 100)
        self.pid_tabs.addTab(self._pid_axis_page(self.pid_px, self.pid_ix, self.pid_dx), "X")
        self.pid_tabs.addTab(self._pid_axis_page(self.pid_py, self.pid_iy, self.pid_dy), "Y")
        pid.layout().addWidget(self.pid_tabs)

        bezier = self.add_card("Bezier curve")
        self.bezier_enabled = QCheckBox()
        self.bezier_strength = IntSliderSpin(0, 100, "%")
        self.bezier_steps = IntSliderSpin(2, 20)
        add_row(bezier, "Enable", self.bezier_enabled)
        add_row(bezier, "Strength", self.bezier_strength)
        add_row(bezier, "Steps", self.bezier_steps)

        tracker = self.add_card("Tracker prediction")
        self.tracker_enabled = QCheckBox()
        self.prediction_time = IntSliderSpin(0, 100, " ms")
        self.velocity_alpha = IntSliderSpin(0, 100, "%")
        self.velocity_deadzone = IntSliderSpin(0, 500, " px/s")
        self.motion_comp = QCheckBox()
        self.motion_ratio = IntSliderSpin(0, 150, "%")
        self.prediction_max_distance = IntSliderSpin(0, 200, " px")
        self.tracker_show = QCheckBox()
        add_row(tracker, "Enable tracker", self.tracker_enabled)
        add_row(tracker, "Prediction lead time", self.prediction_time)
        add_row(tracker, "Velocity EMA alpha", self.velocity_alpha)
        add_row(tracker, "Velocity deadzone", self.velocity_deadzone)
        add_row(tracker, "Screen motion compensation", self.motion_comp)
        add_row(tracker, "Motion compensation ratio", self.motion_ratio)
        add_row(tracker, "Max prediction distance", self.prediction_max_distance)
        add_row(tracker, "Show prediction overlay", self.tracker_show)
        self.finish()

        self._connect()

    def _pid_axis_page(self, p, i, d) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        add_row_card = QFrame(page)
        add_row_card.setObjectName("flatCard")
        card_layout = QVBoxLayout(add_row_card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        add_row(add_row_card, "P reaction", p)
        add_row(add_row_card, "I correction", i)
        add_row(add_row_card, "D stability", d)
        layout.addWidget(add_row_card)
        return page

    def setConfig(self, config) -> None:
        self._config = config
        self._loading = True
        self._refresh_model_list()
        self._update_model_controls()
        self._refresh_class_list()
        self.fov_size.setValue(config.fov_size)
        self.fov_follow.setChecked(config.fov_follow_mouse)
        self.detect_range.setValue(config.detect_range_size)
        self.detect_interval.setValue(int(config.detect_interval * 1000))
        self.confidence.setValue(int(config.min_confidence * 100))
        self.aim_part.setCurrentText(config.aim_part)
        self.mouse_method.setCurrentText(config.mouse_move_method)
        self.always_aim.setChecked(bool(getattr(config, "always_aim", False)))
        self.keep_detecting.setChecked(bool(getattr(config, "keep_detecting", False)))
        self.sticky_target.setChecked(bool(getattr(config, "sticky_target_enabled", True)))
        self.aim_deadzone.setValue(int(getattr(config, "aim_position_deadzone_px", 1.0)))
        self.lock_radius.setValue(int(getattr(config, "lock_retain_radius_px", 48.0)))
        self.lock_time.setValue(int(getattr(config, "lock_retain_time_s", 0.12) * 1000))
        self._refresh_com_ports()
        if getattr(config, "arduino_com_port", ""):
            self.com_combo.setCurrentText(config.arduino_com_port)
        self.xbox_sensitivity.setValue(int(getattr(config, "xbox_sensitivity", 1.0) * 100))
        self.xbox_deadzone.setValue(int(getattr(config, "xbox_deadzone", 0.05) * 100))
        self.pid_px.setValue(int(config.pid_kp_x * 100))
        self.pid_ix.setValue(int(config.pid_ki_x * 100))
        self.pid_dx.setValue(int(config.pid_kd_x * 100))
        self.pid_py.setValue(int(config.pid_kp_y * 100))
        self.pid_iy.setValue(int(config.pid_ki_y * 100))
        self.pid_dy.setValue(int(config.pid_kd_y * 100))
        self.bezier_enabled.setChecked(bool(config.bezier_curve_enabled))
        self.bezier_strength.setValue(int(config.bezier_curve_strength * 100))
        self.bezier_steps.setValue(int(config.bezier_curve_steps))
        self.tracker_enabled.setChecked(bool(config.tracker_enabled))
        self.prediction_time.setValue(int(config.prediction_lead_time_s * 1000))
        self.velocity_alpha.setValue(int(config.velocity_ema_alpha * 100))
        self.velocity_deadzone.setValue(int(config.velocity_deadzone_px_per_s))
        self.motion_comp.setChecked(bool(getattr(config, "screen_motion_compensation_enabled", True)))
        self.motion_ratio.setValue(int(getattr(config, "screen_motion_compensation_ratio", 1.0) * 100))
        self.prediction_max_distance.setValue(int(getattr(config, "prediction_max_distance_px", 20.0)))
        self.tracker_show.setChecked(bool(config.tracker_show_prediction))
        self._update_method_groups(config.mouse_move_method)
        self._update_connection_labels()
        self._loading = False

    def _connect(self) -> None:
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        self.class_combo.currentTextChanged.connect(self._on_class_changed)
        self.open_model_btn.clicked.connect(lambda: open_path(os.path.join(PROJECT_ROOT, "Model")))
        self.fov_size.valueChanged.connect(self._on_fov_changed)
        self.fov_follow.toggled.connect(lambda v: self._set("fov_follow_mouse", v))
        self.detect_range.valueChanged.connect(self._on_detect_range_changed)
        self.detect_interval.valueChanged.connect(lambda v: self._set("detect_interval", v / 1000.0))
        self.confidence.valueChanged.connect(lambda v: self._set("min_confidence", v / 100.0))
        self.aim_part.currentTextChanged.connect(lambda v: self._set("aim_part", v))
        self.mouse_method.currentTextChanged.connect(self._on_mouse_method)
        self.always_aim.toggled.connect(lambda v: self._set("always_aim", v))
        self.keep_detecting.toggled.connect(lambda v: self._set("keep_detecting", v))
        self.sticky_target.toggled.connect(lambda v: self._set("sticky_target_enabled", v))
        self.aim_deadzone.valueChanged.connect(lambda v: self._set("aim_position_deadzone_px", float(v)))
        self.lock_radius.valueChanged.connect(lambda v: self._set("lock_retain_radius_px", float(v)))
        self.lock_time.valueChanged.connect(lambda v: self._set("lock_retain_time_s", v / 1000.0))
        self.refresh_com_btn.clicked.connect(self._refresh_com_ports)
        self.com_combo.currentTextChanged.connect(self._on_com_port)
        self.arduino_connect_btn.clicked.connect(self._on_arduino_connect)
        self.arduino_guide_btn.clicked.connect(self._open_arduino_guide)
        self.arduino_spoof_btn.clicked.connect(self._spoof_arduino)
        self.arduino_verify_btn.clicked.connect(self._verify_arduino)
        self.arduino_test_btn.clicked.connect(self._test_arduino_heart)
        self.xbox_sensitivity.valueChanged.connect(self._on_xbox_sensitivity)
        self.xbox_deadzone.valueChanged.connect(self._on_xbox_deadzone)
        self.xbox_connect_btn.clicked.connect(self._on_xbox_connect)
        self.pid_px.valueChanged.connect(lambda v: self._set("pid_kp_x", v / 100.0))
        self.pid_ix.valueChanged.connect(lambda v: self._set("pid_ki_x", v / 100.0))
        self.pid_dx.valueChanged.connect(lambda v: self._set("pid_kd_x", v / 100.0))
        self.pid_py.valueChanged.connect(lambda v: self._set("pid_kp_y", v / 100.0))
        self.pid_iy.valueChanged.connect(lambda v: self._set("pid_ki_y", v / 100.0))
        self.pid_dy.valueChanged.connect(lambda v: self._set("pid_kd_y", v / 100.0))
        self.bezier_enabled.toggled.connect(lambda v: self._set("bezier_curve_enabled", v))
        self.bezier_strength.valueChanged.connect(lambda v: self._set("bezier_curve_strength", v / 100.0))
        self.bezier_steps.valueChanged.connect(lambda v: self._set("bezier_curve_steps", v))
        self.tracker_enabled.toggled.connect(lambda v: self._set("tracker_enabled", v))
        self.prediction_time.valueChanged.connect(lambda v: self._set("prediction_lead_time_s", v / 1000.0))
        self.velocity_alpha.valueChanged.connect(lambda v: self._set("velocity_ema_alpha", v / 100.0))
        self.velocity_deadzone.valueChanged.connect(lambda v: self._set("velocity_deadzone_px_per_s", float(v)))
        self.motion_comp.toggled.connect(lambda v: self._set("screen_motion_compensation_enabled", v))
        self.motion_ratio.valueChanged.connect(lambda v: self._set("screen_motion_compensation_ratio", v / 100.0))
        self.prediction_max_distance.valueChanged.connect(lambda v: self._set("prediction_max_distance_px", float(v)))
        self.tracker_show.toggled.connect(lambda v: self._set("tracker_show_prediction", v))

    def _set(self, attr: str, value) -> None:
        if self._config is not None and not self._loading:
            setattr(self._config, attr, value)

    def _refresh_model_list(self) -> None:
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self._model_specs = list_model_specs()
        for spec in self._model_specs:
            path = spec.engine_path if os.path.isabs(spec.engine_path) else os.path.join(PROJECT_ROOT, spec.engine_path)
            suffix = "" if os.path.exists(path) else " (missing)"
            self.model_combo.addItem(spec.display_name + suffix, spec.model_id)
        if self._config is not None:
            for i in range(self.model_combo.count()):
                if self.model_combo.itemData(i) == getattr(self._config, "model_id", ""):
                    self.model_combo.setCurrentIndex(i)
                    break
        self.model_combo.blockSignals(False)

    def _update_model_controls(self) -> None:
        if self._config is None:
            return
        apply_model_constraints(self._config)
        spec = get_model_spec(getattr(self._config, "model_id", ""))
        max_size = max(50, min(int(self._config.width), int(self._config.height)))
        if spec and spec.lock_detect_range_to_input:
            self.fov_size.setRange(50, max(50, spec.input_size))
            self.detect_range.setRange(spec.input_size, spec.input_size)
            self.detect_range.setControlsEnabled(False)
        else:
            self.fov_size.setRange(50, max_size)
            self.detect_range.setRange(50, max_size)
            self.detect_range.setControlsEnabled(True)

    def _refresh_class_list(self) -> None:
        self.class_combo.blockSignals(True)
        self.class_combo.clear()
        if self._config is not None:
            spec = get_model_spec(getattr(self._config, "model_id", ""))
            if spec:
                self.class_combo.addItems([label.upper() for label in spec.labels])
                if self._config.active_target_class in spec.labels:
                    self.class_combo.setCurrentIndex(spec.labels.index(self._config.active_target_class))
        self.class_combo.blockSignals(False)

    def _on_model_changed(self) -> None:
        if self._config is None or self._loading:
            return
        model_id = self.model_combo.currentData()
        spec = get_model_spec(model_id)
        if spec is None:
            return
        self._config.model_id = spec.model_id
        self._config.model_path = spec.engine_path
        self._config.model_input_size = spec.input_size
        apply_model_constraints(self._config)
        self._loading = True
        self._update_model_controls()
        self.fov_size.setValue(self._config.fov_size)
        self.detect_range.setValue(self._config.detect_range_size)
        self._refresh_class_list()
        self._loading = False
        window = self.window()
        if hasattr(window, "_refreshTriggerVisibility"):
            window._refreshTriggerVisibility()

    def _on_class_changed(self, text: str) -> None:
        if self._config is not None and not self._loading and text:
            self._config.active_target_class = text.lower()

    def _on_fov_changed(self, value: int) -> None:
        if self._config is None or self._loading:
            return
        self._config.fov_size = value
        apply_model_constraints(self._config)
        if self.fov_size.value() != self._config.fov_size:
            self.fov_size.setValue(self._config.fov_size)

    def _on_detect_range_changed(self, value: int) -> None:
        if self._config is None or self._loading:
            return
        self._config.detect_range_size = value
        apply_model_constraints(self._config)
        if self.detect_range.value() != self._config.detect_range_size:
            self.detect_range.setValue(self._config.detect_range_size)

    def _on_mouse_method(self, text: str) -> None:
        self._set("mouse_move_method", text)
        self._update_method_groups(text)

    def _update_method_groups(self, method: str) -> None:
        self.arduino_group.setVisible(method == "arduino")
        self.xbox_group.setVisible(method == "xbox")

    def _refresh_com_ports(self) -> None:
        current = self.com_combo.currentText()
        self.com_combo.blockSignals(True)
        self.com_combo.clear()
        self.com_combo.addItem("No COM port")
        try:
            import serial.tools.list_ports

            for port in serial.tools.list_ports.comports():
                self.com_combo.addItem(port.device)
        except Exception:
            pass
        if current:
            self.com_combo.setCurrentText(current)
        self.com_combo.blockSignals(False)

    def _on_com_port(self, text: str) -> None:
        if self._config is not None and not self._loading and text != "No COM port":
            self._config.arduino_com_port = text

    def _on_arduino_connect(self) -> None:
        try:
            from win_utils import connect_arduino, disconnect_arduino, is_arduino_connected

            if is_arduino_connected():
                disconnect_arduino()
            else:
                port = self.com_combo.currentText()
                if not port or port == "No COM port":
                    QMessageBox.warning(self, "Arduino", "Select a COM port first.")
                    return
                connect_arduino(port)
        except Exception as exc:
            QMessageBox.warning(self, "Arduino", str(exc))
        self._update_connection_labels()

    def _open_arduino_guide(self) -> None:
        guide = os.path.join(SRC_ROOT, "Arduino_User_Guide.html")
        if os.path.exists(guide):
            QDesktopServices.openUrl(QUrl.fromLocalFile(guide))

    def _spoof_arduino(self) -> None:
        if QMessageBox.question(self, "Spoof device", "Apply Arduino board spoof?") != QMessageBox.StandardButton.Yes:
            return
        try:
            from win_utils.arduino_spoofer import spoof_arduino_board

            success, path = spoof_arduino_board()
            if success:
                QMessageBox.information(self, "Spoof device", "Spoof operation completed.")
            else:
                QMessageBox.warning(self, "Spoof device", f"Spoof operation failed.\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "Spoof device", str(exc))

    def _verify_arduino(self) -> None:
        try:
            from win_utils.arduino_spoofer import verify_spoof

            port = getattr(self._config, "arduino_com_port", "") if self._config else ""
            spoofed, message = verify_spoof(port or None)
            if spoofed:
                QMessageBox.information(self, "Verify spoof", message)
            else:
                QMessageBox.warning(self, "Verify spoof", message)
        except Exception as exc:
            QMessageBox.warning(self, "Verify spoof", str(exc))

    def _test_arduino_heart(self) -> None:
        if QMessageBox.question(self, "Test movement", "Move the Arduino cursor in a heart pattern?") != QMessageBox.StandardButton.Yes:
            return

        def draw() -> None:
            import time
            from win_utils.arduino_mouse import arduino_mouse

            if not arduino_mouse.is_connected():
                port = getattr(self._config, "arduino_com_port", "") if self._config else ""
                if not port or not arduino_mouse.connect(port):
                    return
            points = []
            for index in range(121):
                angle = 2 * math.pi * index / 120
                x = 16 * (math.sin(angle) ** 3)
                y = -(13 * math.cos(angle) - 5 * math.cos(2 * angle) - 2 * math.cos(3 * angle) - math.cos(4 * angle))
                points.append((x * 3.0, y * 3.0))
            for index in range(1, len(points)):
                dx = int(round(points[index][0] - points[index - 1][0]))
                dy = int(round(points[index][1] - points[index - 1][1]))
                if dx or dy:
                    arduino_mouse.move(dx, dy)
                time.sleep(0.015)

        threading.Thread(target=draw, daemon=True).start()

    def _on_xbox_sensitivity(self, value: int) -> None:
        self._set("xbox_sensitivity", value / 100.0)
        try:
            from win_utils import set_xbox_sensitivity

            set_xbox_sensitivity(value / 100.0)
        except Exception:
            pass

    def _on_xbox_deadzone(self, value: int) -> None:
        self._set("xbox_deadzone", value / 100.0)
        try:
            from win_utils import set_xbox_deadzone

            set_xbox_deadzone(value / 100.0)
        except Exception:
            pass

    def _on_xbox_connect(self) -> None:
        try:
            from win_utils import connect_xbox, disconnect_xbox, is_xbox_connected

            if is_xbox_connected():
                disconnect_xbox()
            else:
                connect_xbox()
        except Exception as exc:
            QMessageBox.warning(self, "Xbox", str(exc))
        self._update_connection_labels()

    def _update_connection_labels(self) -> None:
        try:
            from win_utils import is_arduino_connected

            connected = is_arduino_connected()
            self.arduino_status.setText("Connected" if connected else "Disconnected")
            self.arduino_connect_btn.setText("Disconnect" if connected else "Connect")
        except Exception:
            self.arduino_status.setText("Unavailable")
        try:
            from win_utils import is_xbox_available, is_xbox_connected

            if not is_xbox_available():
                self.xbox_status.setText("Unavailable")
                self.xbox_connect_btn.setText("Connect")
            else:
                connected = is_xbox_connected()
                self.xbox_status.setText("Connected" if connected else "Disconnected")
                self.xbox_connect_btn.setText("Disconnect" if connected else "Connect")
        except Exception:
            self.xbox_status.setText("Unavailable")


class TriggerPage(SettingsPage):
    def __init__(self, parent=None) -> None:
        super().__init__("Trigger", parent)
        self._config = None

        self.fire_group = self.add_card("Auto fire")
        self.fire_target = QComboBox()
        self.fire_target.addItems(["head", "body", "both"])
        self.always_fire = QCheckBox()
        self.scope_delay = FloatSpin(0.0, 2.0, 2, 0.01, " s")
        self.fire_interval = FloatSpin(0.01, 1.0, 2, 0.01, " s")
        add_row(self.fire_group, "Auto fire target", self.fire_target)
        add_row(self.fire_group, "Always auto fire", self.always_fire)
        add_row(self.fire_group, "Scope delay", self.scope_delay)
        add_row(self.fire_group, "Fire interval", self.fire_interval)

        self.area_group = self.add_card("Target area")
        self.head_width = IntSliderSpin(10, 100, "%")
        self.head_height = IntSliderSpin(10, 100, "%")
        self.body_width = IntSliderSpin(10, 100, "%")
        add_row(self.area_group, "Head width ratio", self.head_width)
        add_row(self.area_group, "Head height ratio", self.head_height)
        add_row(self.area_group, "Body width ratio", self.body_width)
        self.finish()

        self.fire_target.currentTextChanged.connect(lambda v: self._set("auto_fire_target_part", v))
        self.always_fire.toggled.connect(lambda v: self._set("always_auto_fire", v))
        self.scope_delay.valueChanged.connect(lambda v: self._set("auto_fire_delay", v))
        self.fire_interval.valueChanged.connect(lambda v: self._set("auto_fire_interval", v))
        self.head_width.valueChanged.connect(lambda v: self._set("head_width_ratio", v / 100.0))
        self.head_height.valueChanged.connect(lambda v: self._set("head_height_ratio", v / 100.0))
        self.body_width.valueChanged.connect(lambda v: self._set("body_width_ratio", v / 100.0))

    def setConfig(self, config) -> None:
        self._config = config
        self._loading = True
        self.fire_target.setCurrentText(config.auto_fire_target_part)
        self.always_fire.setChecked(bool(config.always_auto_fire))
        self.scope_delay.setValue(config.auto_fire_delay)
        self.fire_interval.setValue(config.auto_fire_interval)
        self.head_width.setValue(int(config.head_width_ratio * 100))
        self.head_height.setValue(int(config.head_height_ratio * 100))
        self.body_width.setValue(int(config.body_width_ratio * 100))
        self._loading = False
        self.refreshVisibility()

    def refreshVisibility(self) -> None:
        if self._config is None:
            return
        is_cs2 = is_cs2_model(getattr(self._config, "model_id", ""))
        self.fire_target.setVisible(not is_cs2)
        self.area_group.setVisible(not is_cs2)

    def _set(self, attr: str, value) -> None:
        if self._config is not None and not self._loading:
            setattr(self._config, attr, value)


class KeysPage(SettingsPage):
    def __init__(self, parent=None) -> None:
        super().__init__("Keys", parent)
        self._config = None

        aim = self.add_card("Auto aim")
        self.aim_key_1 = KeyBindButton()
        self.aim_key_2 = KeyBindButton()
        self.aim_key_3 = KeyBindButton()
        self.toggle_key = KeyBindButton()
        self.cycle_key = KeyBindButton()
        add_row(aim, "Aim key 1", self.aim_key_1)
        add_row(aim, "Aim key 2", self.aim_key_2)
        add_row(aim, "Aim key 3", self.aim_key_3)
        add_row(aim, "Toggle key", self.toggle_key)
        add_row(aim, "Cycle target key", self.cycle_key)

        fire = self.add_card("Auto fire")
        self.fire_key_1 = KeyBindButton()
        self.fire_key_2 = KeyBindButton()
        add_row(fire, "Auto fire key 1", self.fire_key_1)
        add_row(fire, "Auto fire key 2", self.fire_key_2)
        self.finish()

        self.aim_key_1.keyBound.connect(lambda vk: self._set_aim_key(0, vk))
        self.aim_key_2.keyBound.connect(lambda vk: self._set_aim_key(1, vk))
        self.aim_key_3.keyBound.connect(lambda vk: self._set_aim_key(2, vk))
        self.toggle_key.keyBound.connect(lambda vk: self._set("aim_toggle_key", vk))
        self.cycle_key.keyBound.connect(lambda vk: self._set("cycle_target_key", vk))
        self.fire_key_1.keyBound.connect(lambda vk: self._set("auto_fire_key", vk))
        self.fire_key_2.keyBound.connect(lambda vk: self._set("auto_fire_key2", vk))

    def setConfig(self, config) -> None:
        self._config = config
        keys = list(getattr(config, "AimKeys", [])) + [0, 0, 0]
        self.aim_key_1.setVkCode(keys[0])
        self.aim_key_2.setVkCode(keys[1])
        self.aim_key_3.setVkCode(keys[2])
        self.toggle_key.setVkCode(config.aim_toggle_key)
        self.cycle_key.setVkCode(getattr(config, "cycle_target_key", 0x77))
        self.fire_key_1.setVkCode(config.auto_fire_key)
        self.fire_key_2.setVkCode(config.auto_fire_key2)

    def _set(self, attr: str, value) -> None:
        if self._config is not None:
            setattr(self._config, attr, value)

    def _set_aim_key(self, index: int, vk: int) -> None:
        if self._config is None:
            return
        while len(self._config.AimKeys) <= index:
            self._config.AimKeys.append(0)
        self._config.AimKeys[index] = vk


class ConfigsPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._config = None
        self._config_manager = None

        root = QHBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.config_list = QListWidget(splitter)
        actions = QFrame(splitter)
        actions.setObjectName("settingsCard")
        action_layout = QVBoxLayout(actions)
        action_layout.setContentsMargins(16, 14, 16, 14)
        action_layout.setSpacing(10)

        title = QLabel("Config profiles", actions)
        title.setObjectName("groupTitle")
        action_layout.addWidget(title)
        self.create_btn = QPushButton("Create")
        self.load_btn = QPushButton("Load")
        self.save_btn = QPushButton("Save")
        self.delete_btn = QPushButton("Delete")
        self.rename_btn = QPushButton("Rename")
        self.refresh_btn = QPushButton("Refresh")
        self.import_btn = QPushButton("Import")
        self.export_btn = QPushButton("Export")
        self.open_folder_btn = QPushButton("Open Folder")
        for button in (
            self.create_btn,
            self.load_btn,
            self.save_btn,
            self.delete_btn,
            self.rename_btn,
            self.refresh_btn,
            self.import_btn,
            self.export_btn,
            self.open_folder_btn,
        ):
            action_layout.addWidget(button)
        action_layout.addStretch(1)

        splitter.addWidget(self.config_list)
        splitter.addWidget(actions)
        splitter.setSizes([520, 220])
        root.addWidget(splitter)

        self.create_btn.clicked.connect(self._create)
        self.load_btn.clicked.connect(self._load)
        self.save_btn.clicked.connect(self._save)
        self.delete_btn.clicked.connect(self._delete)
        self.rename_btn.clicked.connect(self._rename)
        self.refresh_btn.clicked.connect(self._refresh)
        self.import_btn.clicked.connect(self._import)
        self.export_btn.clicked.connect(self._export)
        self.open_folder_btn.clicked.connect(self._open_folder)

    def setConfig(self, config) -> None:
        self._config = config

    def setConfigManager(self, manager) -> None:
        self._config_manager = manager
        self._refresh()

    def _selected(self) -> str:
        item = self.config_list.currentItem()
        return item.text() if item else ""

    def _refresh(self) -> None:
        self.config_list.clear()
        if self._config_manager is None:
            return
        for name in self._config_manager.get_config_list():
            self.config_list.addItem(name)

    def _create(self) -> None:
        name, ok = QInputDialog.getText(self, "Create config", "Config name:")
        if ok and name and self._config_manager and self._config:
            self._config_manager.save_config(self._config, name)
            self._refresh()

    def _load(self) -> None:
        name = self._selected()
        if not name:
            QMessageBox.warning(self, "Config", "Select a config first.")
            return
        if self._config_manager and self._config and self._config_manager.load_config(self._config, name):
            window = self.window()
            if hasattr(window, "_refreshAllPages"):
                window._refreshAllPages()
            QMessageBox.information(self, "Config", "Config loaded.")
        else:
            QMessageBox.warning(self, "Config", "Config load failed.")

    def _save(self) -> None:
        name = self._selected()
        if not name:
            QMessageBox.warning(self, "Config", "Select a config first.")
            return
        if QMessageBox.question(self, "Config", f"Overwrite {name}?") != QMessageBox.StandardButton.Yes:
            return
        if self._config_manager and self._config:
            self._config_manager.save_config(self._config, name)

    def _delete(self) -> None:
        name = self._selected()
        if not name:
            QMessageBox.warning(self, "Config", "Select a config first.")
            return
        if QMessageBox.question(self, "Config", f"Delete {name}?") != QMessageBox.StandardButton.Yes:
            return
        if self._config_manager:
            self._config_manager.delete_config(name)
            self._refresh()

    def _rename(self) -> None:
        old_name = self._selected()
        if not old_name:
            QMessageBox.warning(self, "Config", "Select a config first.")
            return
        new_name, ok = QInputDialog.getText(self, "Rename config", "New name:", text=old_name)
        if ok and new_name and self._config_manager:
            self._config_manager.rename_config(old_name, new_name)
            self._refresh()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import config", "", "JSON Files (*.json)")
        if path and self._config_manager:
            self._config_manager.import_config(path)
            self._refresh()

    def _export(self) -> None:
        name = self._selected()
        if not name:
            QMessageBox.warning(self, "Config", "Select a config first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export config", f"{name}.json", "JSON Files (*.json)")
        if path and self._config_manager:
            self._config_manager.export_config(name, path)

    def _open_folder(self) -> None:
        if self._config_manager:
            open_path(os.path.abspath(self._config_manager.configs_dir))


class OtherPage(SettingsPage):
    def __init__(self, parent=None) -> None:
        super().__init__("Other", parent)
        self._config = None

        program = self.add_card("Program")
        self.show_console = QCheckBox()
        self.refresh_runtime_btn = QPushButton("Refresh Runtime Settings")
        self.save_btn = QPushButton("Save Config")
        self.exit_btn = QPushButton("Exit and Save")
        add_row(program, "Show console", self.show_console)
        add_row(program, "Apply runtime settings", self.refresh_runtime_btn)
        add_row(program, "Save current config", self.save_btn)
        add_row(program, "Exit", self.exit_btn)

        language = self.add_card("Language")
        self.language_combo = QComboBox()
        try:
            from core.language_manager import language_manager

            self.language_combo.addItems(language_manager.get_available_languages())
            self.language_combo.setCurrentText(language_manager.get_current_language())
        except Exception:
            self.language_combo.addItem("English_English")
        add_row(language, "Language", self.language_combo)

        about = self.add_card("About")
        self.version_label = QLabel(f"Axiom v{__version__}")
        self.discord_btn = QPushButton("Discord")
        self.github_btn = QPushButton("GitHub")
        self.donate_btn = QPushButton("Donate")
        add_row(about, "Version", self.version_label)
        links = QWidget()
        links_layout = QHBoxLayout(links)
        links_layout.setContentsMargins(0, 0, 0, 0)
        links_layout.addWidget(self.discord_btn)
        links_layout.addWidget(self.github_btn)
        links_layout.addWidget(self.donate_btn)
        add_row(about, "Links", links)
        self.finish()

        self.show_console.toggled.connect(self._on_show_console)
        self.refresh_runtime_btn.clicked.connect(self._refresh_runtime)
        self.save_btn.clicked.connect(self._save_config)
        self.exit_btn.clicked.connect(self._exit_save)
        self.language_combo.currentTextChanged.connect(self._set_language)
        self.discord_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://discord.gg/h4dEh3b8Bt")))
        self.github_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/iisHong0w0/Axiom-AI-Aimbot")))
        self.donate_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(SRC_ROOT, "MVP.html"))))

    def setConfig(self, config) -> None:
        self._config = config
        self._loading = True
        self.show_console.setChecked(bool(config.show_console))
        self._loading = False

    def _on_show_console(self, checked: bool) -> None:
        if self._config is not None and not self._loading:
            self._config.show_console = bool(checked)
        try:
            from win_utils.console import hide_console, show_console

            if checked:
                show_console()
            else:
                hide_console()
        except Exception:
            pass

    def _refresh_runtime(self) -> None:
        window = self.window()
        if hasattr(window, "refreshRuntimeSettings"):
            token = window.refreshRuntimeSettings()
            QMessageBox.information(self, "Runtime", f"Runtime refresh token: {token}")

    def _save_config(self) -> None:
        if self._config is not None:
            save_config(self._config)
            QMessageBox.information(self, "Config", "Config saved.")

    def _exit_save(self) -> None:
        self._save_config()
        self.window().close()

    def _set_language(self, language: str) -> None:
        try:
            from core.language_manager import language_manager

            language_manager.set_language(language)
        except Exception:
            pass


class AxiomWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._config = None
        self._configManager = None
        self.setWindowTitle(f"Axiom v{__version__}")
        self.resize(980, 720)

        logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logo.png")
        if os.path.exists(logo_path):
            self.setWindowIcon(QIcon(logo_path))

        central = QWidget(self)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.nav = QListWidget(central)
        self.nav.setObjectName("navigation")
        self.nav.setFixedWidth(170)
        self.stack = QStackedWidget(central)
        root.addWidget(self.nav)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.displayInterface = VisualsPage(self)
        self.aimInterface = AimPage(self)
        self.triggerInterface = TriggerPage(self)
        self.keysInterface = KeysPage(self)
        self.configInterface = ConfigsPage(self)
        self.otherInterface = OtherPage(self)

        self._pages = [
            ("Display", self.displayInterface),
            ("Aim", self.aimInterface),
            ("Trigger", self.triggerInterface),
            ("Keys", self.keysInterface),
            ("Configs", self.configInterface),
            ("Other", self.otherInterface),
        ]
        for label, page in self._pages:
            self.nav.addItem(QListWidgetItem(label))
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(1)

    def setConfig(self, config) -> None:
        self._config = config
        app = QApplication.instance()
        if app is not None:
            app.setProperty("axiom_dark_mode", bool(getattr(config, "dark_mode", False)))
        for _, page in self._pages:
            if hasattr(page, "setConfig"):
                page.setConfig(config)
        self._applyThemeStyles()
        self._forceWindowsTitleBarColor(isDark=_is_dark(config))

    def setConfigManager(self, manager) -> None:
        self._configManager = manager
        self.configInterface.setConfigManager(manager)

    def _refreshAllPages(self) -> None:
        if self._config is not None:
            self.setConfig(self._config)

    def _refreshTriggerVisibility(self) -> None:
        self.triggerInterface.refreshVisibility()

    def refreshRuntimeSettings(self) -> int:
        if self._config is None:
            return 0
        return bump_runtime_refresh_token(self._config)

    def _applyThemeStyles(self) -> None:
        dark = bool(getattr(self._config, "dark_mode", False))
        app = QApplication.instance()
        if app is not None:
            app.setProperty("axiom_dark_mode", dark)

        if dark:
            bg = "#1f2328"
            panel = "#2b3036"
            panel_alt = "#252a30"
            text = "#f0f3f6"
            muted = "#a8b0b8"
            border = "#3d444d"
            selected = "#3b6388"
        else:
            bg = "#f4f6f8"
            panel = "#ffffff"
            panel_alt = "#eef2f6"
            text = "#1f2328"
            muted = "#687076"
            border = "#d0d7de"
            selected = "#d7e8fa"

        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{
                background: {bg};
                color: {text};
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 12px;
            }}
            QListWidget#navigation {{
                background: {panel_alt};
                border: none;
                border-right: 1px solid {border};
                padding: 10px;
            }}
            QListWidget#navigation::item {{
                padding: 10px 12px;
                border-radius: 4px;
                margin: 2px 0;
            }}
            QListWidget#navigation::item:selected {{
                background: {selected};
            }}
            QFrame#settingsCard {{
                background: {panel};
                border: 1px solid {border};
                border-radius: 6px;
            }}
            QLabel#pageTitle {{
                font-size: 22px;
                font-weight: 600;
                margin-bottom: 4px;
            }}
            QLabel#groupTitle {{
                font-size: 15px;
                font-weight: 600;
            }}
            QLabel#rowLabel {{
                font-weight: 500;
            }}
            QLabel#rowDescription {{
                color: {muted};
            }}
            QPushButton, QComboBox, QSpinBox, QDoubleSpinBox {{
                min-height: 26px;
            }}
            QLineEdit, QTextEdit, QTextBrowser, QListWidget, QComboBox, QSpinBox, QDoubleSpinBox {{
                background: {panel};
                color: {text};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 2px 5px;
            }}
            QPushButton {{
                background: {panel_alt};
                color: {text};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 5px 10px;
            }}
            QPushButton:hover {{
                background: {selected};
            }}
            QScrollArea {{
                border: none;
            }}
            """
        )

    def _forceWindowsTitleBarColor(self, isDark: bool = False) -> None:
        if sys.platform != "win32":
            return
        try:
            dwmapi = WinDLL("dwmapi")
            hwnd = int(self.winId())
            value = c_int(1 if isDark else 0)
            dwmapi.DwmSetWindowAttribute(hwnd, DWORD(20), byref(value), 4)
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        if self._config is not None:
            try:
                save_config(self._config)
            except Exception as exc:
                print(f"Failed to save config on close: {exc}")
        super().closeEvent(event)

"""Native PyQt6 settings window."""

from __future__ import annotations

import os
import sys
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
    tr,
)


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")


def _is_dark(config) -> bool:
    return bool(getattr(config, "dark_mode", False))


class VisualsPage(SettingsPage):
    def __init__(self, parent=None) -> None:
        super().__init__(tr("display", "Display"), parent)
        self._config = None

        self.display_card = self.add_card(tr("overlay", "Overlay"))
        self.show_fov = QCheckBox()
        self.show_boxes = QCheckBox()
        self.show_confidence = QCheckBox()
        self.show_status = QCheckBox()
        self.show_detect_range = QCheckBox()
        self.show_fov_label = add_row(self.display_card, "", self.show_fov)
        self.show_boxes_label = add_row(self.display_card, "", self.show_boxes)
        self.show_confidence_label = add_row(self.display_card, "", self.show_confidence)
        self.show_status_label = add_row(self.display_card, "", self.show_status)
        self.show_detect_range_label = add_row(self.display_card, "", self.show_detect_range)

        self.appearance_card = self.add_card(tr("appearance_options", "Appearance"))
        self.dark_mode = QCheckBox()
        self.enable_acrylic = QCheckBox()
        self.window_alpha = IntSliderSpin(0, 255)
        self.dark_mode_label = add_row(self.appearance_card, "", self.dark_mode)
        self.enable_acrylic_label = add_row(self.appearance_card, "", self.enable_acrylic)
        self.window_alpha_label = add_row(self.appearance_card, "", self.window_alpha)
        self.finish()
        self.retranslateUi()

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

    def retranslateUi(self) -> None:
        self.title_label.setText(tr("display", "Display"))
        self.display_card.title_label.setText(tr("overlay", "Overlay"))  # type: ignore[attr-defined]
        self.appearance_card.title_label.setText(tr("appearance_options", "Appearance"))  # type: ignore[attr-defined]
        for label, key, default in (
            (self.show_fov_label, "show_fov", "Show FOV"),
            (self.show_boxes_label, "show_boxes", "Show boxes"),
            (self.show_confidence_label, "show_confidence", "Show confidence"),
            (self.show_status_label, "show_status_panel", "Show status panel"),
            (self.show_detect_range_label, "show_detect_range", "Show detect range"),
            (self.dark_mode_label, "use_dark_mode", "Dark mode"),
            (self.enable_acrylic_label, "enable_acrylic", "Enable acrylic"),
            (self.window_alpha_label, "acrylic_window_alpha", "Acrylic window alpha"),
        ):
            if label is not None:
                label.setText(tr(key, default))


class AimPage(SettingsPage):
    def __init__(self, parent=None) -> None:
        super().__init__(tr("aim", "Aim"), parent)
        self._config = None
        self._model_specs = []

        self.model_card = self.add_card(tr("model_settings", "Model"))
        self.model_combo = QComboBox()
        self.class_combo = QComboBox()
        self.open_model_btn = QPushButton()
        self.model_label = add_row(self.model_card, "", self.model_combo)
        self.class_label = add_row(self.model_card, "", self.class_combo)
        self.model_folder_label = add_row(self.model_card, "", self.open_model_btn)

        self.fov_card = self.add_card(tr("fov_and_detect_range", "FOV and detection"))
        self.fov_size = IntSliderSpin(50, 500, " px")
        self.fov_follow = QCheckBox()
        self.detect_range = IntSliderSpin(50, 1080, " px")
        self.fov_size_label = add_row(self.fov_card, "", self.fov_size)
        self.fov_follow_label = add_row(self.fov_card, "", self.fov_follow)
        self.detect_range_label = add_row(self.fov_card, "", self.detect_range)

        self.general_card = self.add_card(tr("general_params", "General"))
        self.detect_interval = IntSliderSpin(1, 100, " ms")
        self.confidence = IntSliderSpin(1, 100, "%")
        self.aim_part = QComboBox()
        self.aim_part.addItems(["head", "body", "both"])
        self.mouse_method = QComboBox()
        self.mouse_method.addItems(["ddxoft"])
        self.always_aim = QCheckBox()
        self.keep_detecting = QCheckBox()
        self.sticky_target = QCheckBox()
        self.aim_deadzone = IntSliderSpin(0, 20, " px")
        self.lock_radius = IntSliderSpin(8, 300, " px")
        self.lock_time = IntSliderSpin(0, 500, " ms")
        self.detect_interval_label = add_row(self.general_card, "", self.detect_interval)
        self.confidence_label = add_row(self.general_card, "", self.confidence)
        self.aim_part_label = add_row(self.general_card, "", self.aim_part)
        self.mouse_method_label = add_row(self.general_card, "", self.mouse_method)
        self.always_aim_label = add_row(self.general_card, "", self.always_aim)
        self.keep_detecting_label = add_row(self.general_card, "", self.keep_detecting)
        self.sticky_target_label = add_row(self.general_card, "", self.sticky_target)
        self.aim_deadzone_label = add_row(self.general_card, "", self.aim_deadzone)
        self.lock_radius_label = add_row(self.general_card, "", self.lock_radius)
        self.lock_time_label = add_row(self.general_card, "", self.lock_time)

        self.pid_card = self.add_card(tr("pid", "PID"))
        self.pid_tabs = QTabWidget()
        self.pid_px = IntSliderSpin(0, 100)
        self.pid_ix = IntSliderSpin(0, 100)
        self.pid_dx = IntSliderSpin(0, 100)
        self.pid_py = IntSliderSpin(0, 100)
        self.pid_iy = IntSliderSpin(0, 100)
        self.pid_dy = IntSliderSpin(0, 100)
        self.pid_tabs.addTab(self._pid_axis_page(self.pid_px, self.pid_ix, self.pid_dx), "X")
        self.pid_tabs.addTab(self._pid_axis_page(self.pid_py, self.pid_iy, self.pid_dy), "Y")
        self.pid_card.layout().addWidget(self.pid_tabs)

        self.bezier_card = self.add_card(tr("bezier_curve", "Bezier curve"))
        self.bezier_enabled = QCheckBox()
        self.bezier_strength = IntSliderSpin(0, 100, "%")
        self.bezier_steps = IntSliderSpin(2, 20)
        self.bezier_enabled_label = add_row(self.bezier_card, "", self.bezier_enabled)
        self.bezier_strength_label = add_row(self.bezier_card, "", self.bezier_strength)
        self.bezier_steps_label = add_row(self.bezier_card, "", self.bezier_steps)

        self.tracker_card = self.add_card(tr("tracker_prediction", "Tracker prediction"))
        self.tracker_enabled = QCheckBox()
        self.prediction_time = IntSliderSpin(0, 100, " ms")
        self.velocity_alpha = IntSliderSpin(0, 100, "%")
        self.velocity_deadzone = IntSliderSpin(0, 500, " px/s")
        self.motion_comp = QCheckBox()
        self.motion_ratio = IntSliderSpin(0, 150, "%")
        self.prediction_max_distance = IntSliderSpin(0, 200, " px")
        self.tracker_show = QCheckBox()
        self.tracker_enabled_label = add_row(self.tracker_card, "", self.tracker_enabled)
        self.prediction_time_label = add_row(self.tracker_card, "", self.prediction_time)
        self.velocity_alpha_label = add_row(self.tracker_card, "", self.velocity_alpha)
        self.velocity_deadzone_label = add_row(self.tracker_card, "", self.velocity_deadzone)
        self.motion_comp_label = add_row(self.tracker_card, "", self.motion_comp)
        self.motion_ratio_label = add_row(self.tracker_card, "", self.motion_ratio)
        self.prediction_max_distance_label = add_row(self.tracker_card, "", self.prediction_max_distance)
        self.tracker_show_label = add_row(self.tracker_card, "", self.tracker_show)
        self.finish()
        self.retranslateUi()

        self._connect()

    def _pid_axis_page(self, p, i, d) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        add_row_card = QFrame(page)
        add_row_card.setObjectName("flatCard")
        card_layout = QVBoxLayout(add_row_card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        add_row(add_row_card, tr("reaction_speed_p", "P reaction"), p)
        add_row(add_row_card, tr("error_correction_i", "I correction"), i)
        add_row(add_row_card, tr("stability_suppression_d", "D stability"), d)
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
        self._loading = False

    def retranslateUi(self) -> None:
        self.title_label.setText(tr("aim", "Aim"))
        for card, key, default in (
            (self.model_card, "model_settings", "Model"),
            (self.fov_card, "fov_and_detect_range", "FOV and detection"),
            (self.general_card, "general_params", "General"),
            (self.pid_card, "pid", "PID"),
            (self.bezier_card, "bezier_curve", "Bezier curve"),
            (self.tracker_card, "tracker_prediction", "Tracker prediction"),
        ):
            card.title_label.setText(tr(key, default))  # type: ignore[attr-defined]
        self.open_model_btn.setText(tr("open_model_folder", "Open Model Folder"))
        for label, key, default in (
            (self.model_label, "model", "Model"),
            (self.class_label, "active_target_class", "Active target class"),
            (self.model_folder_label, "model_folder", "Model folder"),
            (self.fov_size_label, "fov_size", "FOV size"),
            (self.fov_follow_label, "fov_follow_mouse", "FOV follows mouse"),
            (self.detect_range_label, "detect_range_size", "Detect range size"),
            (self.detect_interval_label, "detect_interval", "Detect interval"),
            (self.confidence_label, "minimum_confidence", "Minimum confidence"),
            (self.aim_part_label, "aim_part", "Aim part"),
            (self.mouse_method_label, "mouse_move_method", "Mouse move method"),
            (self.always_aim_label, "always_aim_label", "Always aim"),
            (self.keep_detecting_label, "keep_detecting_label", "Keep detecting"),
            (self.sticky_target_label, "sticky_target_label", "Sticky target"),
            (self.aim_deadzone_label, "aim_position_deadzone_px", "Aim deadzone"),
            (self.lock_radius_label, "lock_retain_radius_px", "Lock retain radius"),
            (self.lock_time_label, "lock_retain_time_s", "Lock retain time"),
            (self.bezier_enabled_label, "enable", "Enable"),
            (self.bezier_strength_label, "strength", "Strength"),
            (self.bezier_steps_label, "steps", "Steps"),
            (self.tracker_enabled_label, "enable_tracker", "Enable tracker"),
            (self.prediction_time_label, "prediction_lead_time", "Prediction lead time"),
            (self.velocity_alpha_label, "velocity_ema_alpha", "Velocity EMA alpha"),
            (self.velocity_deadzone_label, "velocity_deadzone", "Velocity deadzone"),
            (self.motion_comp_label, "screen_motion_compensation", "Screen motion compensation"),
            (self.motion_ratio_label, "motion_compensation_ratio", "Motion compensation ratio"),
            (self.prediction_max_distance_label, "prediction_max_distance_px", "Max prediction distance"),
            (self.tracker_show_label, "show_prediction_overlay", "Show prediction overlay"),
        ):
            if label is not None:
                label.setText(tr(key, default))

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


class TriggerPage(SettingsPage):
    def __init__(self, parent=None) -> None:
        super().__init__(tr("trigger", "Trigger"), parent)
        self._config = None

        self.fire_group = self.add_card(tr("auto_fire", "Auto fire"))
        self.fire_target = QComboBox()
        self.fire_target.addItems(["head", "body", "both"])
        self.always_fire = QCheckBox()
        self.scope_delay = FloatSpin(0.0, 2.0, 2, 0.01, " s")
        self.fire_interval = FloatSpin(0.01, 1.0, 2, 0.01, " s")
        self.fire_target_label = add_row(self.fire_group, "", self.fire_target)
        self.always_fire_label = add_row(self.fire_group, "", self.always_fire)
        self.scope_delay_label = add_row(self.fire_group, "", self.scope_delay)
        self.fire_interval_label = add_row(self.fire_group, "", self.fire_interval)

        self.area_group = self.add_card(tr("target_area", "Target area"))
        self.head_width = IntSliderSpin(10, 100, "%")
        self.head_height = IntSliderSpin(10, 100, "%")
        self.body_width = IntSliderSpin(10, 100, "%")
        self.head_width_label = add_row(self.area_group, "", self.head_width)
        self.head_height_label = add_row(self.area_group, "", self.head_height)
        self.body_width_label = add_row(self.area_group, "", self.body_width)
        self.finish()
        self.retranslateUi()

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

    def retranslateUi(self) -> None:
        self.title_label.setText(tr("trigger", "Trigger"))
        self.fire_group.title_label.setText(tr("auto_fire", "Auto fire"))  # type: ignore[attr-defined]
        self.area_group.title_label.setText(tr("target_area", "Target area"))  # type: ignore[attr-defined]
        for label, key, default in (
            (self.fire_target_label, "auto_fire_target", "Auto fire target"),
            (self.always_fire_label, "always_auto_fire", "Always auto fire"),
            (self.scope_delay_label, "scope_delay", "Scope delay"),
            (self.fire_interval_label, "fire_interval", "Fire interval"),
            (self.head_width_label, "head_width_ratio", "Head width ratio"),
            (self.head_height_label, "head_height_ratio", "Head height ratio"),
            (self.body_width_label, "body_width_ratio", "Body width ratio"),
        ):
            if label is not None:
                label.setText(tr(key, default))


class KeysPage(SettingsPage):
    def __init__(self, parent=None) -> None:
        super().__init__(tr("keys", "Keys"), parent)
        self._config = None

        self.aim_card = self.add_card(tr("auto_aim", "Auto aim"))
        self.aim_key_1 = KeyBindButton()
        self.aim_key_2 = KeyBindButton()
        self.aim_key_3 = KeyBindButton()
        self.toggle_key = KeyBindButton()
        self.cycle_key = KeyBindButton()
        self.aim_key_1_label = add_row(self.aim_card, "", self.aim_key_1)
        self.aim_key_2_label = add_row(self.aim_card, "", self.aim_key_2)
        self.aim_key_3_label = add_row(self.aim_card, "", self.aim_key_3)
        self.toggle_key_label = add_row(self.aim_card, "", self.toggle_key)
        self.cycle_key_label = add_row(self.aim_card, "", self.cycle_key)

        self.fire_card = self.add_card(tr("auto_fire", "Auto fire"))
        self.fire_key_1 = KeyBindButton()
        self.fire_key_2 = KeyBindButton()
        self.fire_key_1_label = add_row(self.fire_card, "", self.fire_key_1)
        self.fire_key_2_label = add_row(self.fire_card, "", self.fire_key_2)
        self.finish()
        self.retranslateUi()

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

    def retranslateUi(self) -> None:
        self.title_label.setText(tr("keys", "Keys"))
        self.aim_card.title_label.setText(tr("auto_aim", "Auto aim"))  # type: ignore[attr-defined]
        self.fire_card.title_label.setText(tr("auto_fire", "Auto fire"))  # type: ignore[attr-defined]
        for label, key, default in (
            (self.aim_key_1_label, "aim_key_1", "Aim key 1"),
            (self.aim_key_2_label, "aim_key_2", "Aim key 2"),
            (self.aim_key_3_label, "aim_key_3", "Aim key 3"),
            (self.toggle_key_label, "toggle_key", "Toggle key"),
            (self.cycle_key_label, "cycle_target_key", "Cycle target key"),
            (self.fire_key_1_label, "auto_fire_key_1", "Auto fire key 1"),
            (self.fire_key_2_label, "auto_fire_key_2", "Auto fire key 2"),
        ):
            if label is not None:
                label.setText(tr(key, default))
        for button in (
            self.aim_key_1,
            self.aim_key_2,
            self.aim_key_3,
            self.toggle_key,
            self.cycle_key,
            self.fire_key_1,
            self.fire_key_2,
        ):
            button.refreshText()

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

        self.title_label = QLabel(actions)
        self.title_label.setObjectName("groupTitle")
        action_layout.addWidget(self.title_label)
        self.create_btn = QPushButton()
        self.load_btn = QPushButton()
        self.save_btn = QPushButton()
        self.delete_btn = QPushButton()
        self.rename_btn = QPushButton()
        self.refresh_btn = QPushButton()
        self.import_btn = QPushButton()
        self.export_btn = QPushButton()
        self.open_folder_btn = QPushButton()
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
        self.retranslateUi()

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
        name, ok = QInputDialog.getText(
            self,
            tr("create_config", "Create config"),
            tr("config_name_prompt", "Config name:"),
        )
        if ok and name and self._config_manager and self._config:
            self._config_manager.save_config(self._config, name)
            self._refresh()

    def _load(self) -> None:
        name = self._selected()
        if not name:
            QMessageBox.warning(self, tr("config_manager", "Config"), tr("select_config_first", "Select a config first."))
            return
        if self._config_manager and self._config and self._config_manager.load_config(self._config, name):
            window = self.window()
            if hasattr(window, "_refreshAllPages"):
                window._refreshAllPages()
            QMessageBox.information(self, tr("config_manager", "Config"), tr("config_loaded_message", "Config loaded."))
        else:
            QMessageBox.warning(self, tr("config_manager", "Config"), tr("config_load_failed_message", "Config load failed."))

    def _save(self) -> None:
        name = self._selected()
        if not name:
            QMessageBox.warning(self, tr("config_manager", "Config"), tr("select_config_first", "Select a config first."))
            return
        prompt = tr("overwrite_config_prompt", "Overwrite {name}?").format(name=name)
        if QMessageBox.question(self, tr("config_manager", "Config"), prompt) != QMessageBox.StandardButton.Yes:
            return
        if self._config_manager and self._config:
            self._config_manager.save_config(self._config, name)

    def _delete(self) -> None:
        name = self._selected()
        if not name:
            QMessageBox.warning(self, tr("config_manager", "Config"), tr("select_config_first", "Select a config first."))
            return
        prompt = tr("delete_config_prompt", "Delete {name}?").format(name=name)
        if QMessageBox.question(self, tr("config_manager", "Config"), prompt) != QMessageBox.StandardButton.Yes:
            return
        if self._config_manager:
            self._config_manager.delete_config(name)
            self._refresh()

    def _rename(self) -> None:
        old_name = self._selected()
        if not old_name:
            QMessageBox.warning(self, tr("config_manager", "Config"), tr("select_config_first", "Select a config first."))
            return
        new_name, ok = QInputDialog.getText(
            self,
            tr("rename_config_title", "Rename config"),
            tr("new_name_prompt", "New name:"),
            text=old_name,
        )
        if ok and new_name and self._config_manager:
            self._config_manager.rename_config(old_name, new_name)
            self._refresh()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("import_config", "Import config"),
            "",
            tr("json_files_filter", "JSON Files (*.json)"),
        )
        if path and self._config_manager:
            self._config_manager.import_config(path)
            self._refresh()

    def _export(self) -> None:
        name = self._selected()
        if not name:
            QMessageBox.warning(self, tr("config_manager", "Config"), tr("select_config_first", "Select a config first."))
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("export_config", "Export config"),
            f"{name}.json",
            tr("json_files_filter", "JSON Files (*.json)"),
        )
        if path and self._config_manager:
            self._config_manager.export_config(name, path)

    def _open_folder(self) -> None:
        if self._config_manager:
            open_path(os.path.abspath(self._config_manager.configs_dir))

    def retranslateUi(self) -> None:
        self.title_label.setText(tr("config_profiles", "Config profiles"))
        self.create_btn.setText(tr("create_config", "Create"))
        self.load_btn.setText(tr("load_config", "Load"))
        self.save_btn.setText(tr("save_config", "Save"))
        self.delete_btn.setText(tr("delete_config", "Delete"))
        self.rename_btn.setText(tr("rename_config", "Rename"))
        self.refresh_btn.setText(tr("refresh", "Refresh"))
        self.import_btn.setText(tr("import_config", "Import"))
        self.export_btn.setText(tr("export_config", "Export"))
        self.open_folder_btn.setText(tr("open_config_folder", "Open Folder"))


class OtherPage(SettingsPage):
    def __init__(self, parent=None) -> None:
        super().__init__(tr("other", "Other"), parent)
        self._config = None

        self.program_card = self.add_card(tr("program", "Program"))
        self.show_console = QCheckBox()
        self.refresh_runtime_btn = QPushButton()
        self.save_btn = QPushButton()
        self.exit_btn = QPushButton()
        self.show_console_label = add_row(self.program_card, "", self.show_console)
        self.refresh_runtime_label = add_row(self.program_card, "", self.refresh_runtime_btn)
        self.save_config_label = add_row(self.program_card, "", self.save_btn)
        self.exit_label = add_row(self.program_card, "", self.exit_btn)

        self.language_card = self.add_card(tr("language", "Language"))
        self.language_combo = QComboBox()
        try:
            from core.language_manager import language_manager

            self.language_combo.addItems(language_manager.get_available_languages())
            self.language_combo.setCurrentText(language_manager.get_current_language())
        except Exception:
            self.language_combo.addItem("English_English")
        self.language_label = add_row(self.language_card, "", self.language_combo)

        self.about_card = self.add_card(tr("about", "About"))
        self.version_label = QLabel(f"Axiom v{__version__}")
        self.discord_btn = QPushButton()
        self.github_btn = QPushButton()
        self.donate_btn = QPushButton()
        self.version_row_label = add_row(self.about_card, "", self.version_label)
        links = QWidget()
        links_layout = QHBoxLayout(links)
        links_layout.setContentsMargins(0, 0, 0, 0)
        links_layout.addWidget(self.discord_btn)
        links_layout.addWidget(self.github_btn)
        links_layout.addWidget(self.donate_btn)
        self.links_label = add_row(self.about_card, "", links)
        self.finish()
        self.retranslateUi()

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
            QMessageBox.information(
                self,
                tr("runtime", "Runtime"),
                tr("runtime_refresh_token", "Runtime refresh token: {token}").format(token=token),
            )

    def _save_config(self) -> None:
        if self._config is not None:
            save_config(self._config)
            QMessageBox.information(self, tr("config_manager", "Config"), tr("config_saved", "Config saved."))

    def _exit_save(self) -> None:
        self._save_config()
        self.window().close()

    def _set_language(self, language: str) -> None:
        try:
            from core.language_manager import language_manager

            language_manager.set_language(language)
            window = self.window()
            if hasattr(window, "_retranslateUi"):
                window._retranslateUi()
        except Exception:
            pass

    def retranslateUi(self) -> None:
        self.title_label.setText(tr("other", "Other"))
        for card, key, default in (
            (self.program_card, "program", "Program"),
            (self.language_card, "language", "Language"),
            (self.about_card, "about", "About"),
        ):
            card.title_label.setText(tr(key, default))  # type: ignore[attr-defined]
        self.refresh_runtime_btn.setText(tr("apply_runtime_settings", "Refresh Runtime Settings"))
        self.save_btn.setText(tr("save_config", "Save Config"))
        self.exit_btn.setText(tr("exit_and_save", "Exit and Save"))
        self.discord_btn.setText(tr("discord", "Discord"))
        self.github_btn.setText(tr("github", "GitHub"))
        self.donate_btn.setText(tr("donate", "Donate"))
        for label, key, default in (
            (self.show_console_label, "show_console", "Show console"),
            (self.refresh_runtime_label, "apply_runtime_settings", "Apply runtime settings"),
            (self.save_config_label, "save_current_config", "Save current config"),
            (self.exit_label, "exit", "Exit"),
            (self.language_label, "language", "Language"),
            (self.version_row_label, "version", "Version"),
            (self.links_label, "links", "Links"),
        ):
            if label is not None:
                label.setText(tr(key, default))


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
            ("display", "Display", self.displayInterface),
            ("aim", "Aim", self.aimInterface),
            ("trigger", "Trigger", self.triggerInterface),
            ("keys", "Keys", self.keysInterface),
            ("configs", "Configs", self.configInterface),
            ("other", "Other", self.otherInterface),
        ]
        for key, default, page in self._pages:
            self.nav.addItem(QListWidgetItem(tr(key, default)))
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(1)

    def setConfig(self, config) -> None:
        self._config = config
        app = QApplication.instance()
        if app is not None:
            app.setProperty("axiom_dark_mode", bool(getattr(config, "dark_mode", False)))
        for _, _, page in self._pages:
            if hasattr(page, "setConfig"):
                page.setConfig(config)
        self._retranslateUi()
        self._applyThemeStyles()
        self._forceWindowsTitleBarColor(isDark=_is_dark(config))

    def setConfigManager(self, manager) -> None:
        self._configManager = manager
        self.configInterface.setConfigManager(manager)

    def _refreshAllPages(self) -> None:
        if self._config is not None:
            self.setConfig(self._config)

    def _retranslateUi(self) -> None:
        self.setWindowTitle(tr("window_title", f"Axiom v{__version__}"))
        for index, (key, default, page) in enumerate(self._pages):
            item = self.nav.item(index)
            if item is not None:
                item.setText(tr(key, default))
            if hasattr(page, "retranslateUi"):
                page.retranslateUi()

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

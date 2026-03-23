"""Configuration model and JSON persistence helpers."""

from __future__ import annotations

import ctypes
import json
import os
from typing import Any, Dict, List

from .model_registry import ModelSpec, get_default_model_spec, get_model_spec, resolve_model_spec_from_path

LEGACY_CONFIG_KEYS = {
    "single_target_mode",
    "tracker_prediction_time",
    "tracker_smoothing_factor",
    "tracker_stop_threshold",
    "dml_cpu_fallback",
}
VALID_CAPTURE_BACKENDS = {"auto", "dxcam"}


def _get_screen_size() -> tuple[int, int]:
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def drop_legacy_config_keys(data: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(data)
    for key in LEGACY_CONFIG_KEYS:
        sanitized.pop(key, None)
    return sanitized


def migrate_config_data(data: Dict[str, Any]) -> Dict[str, Any]:
    migrated = dict(data)

    if "single_target_mode" in migrated and "sticky_target_enabled" not in migrated:
        migrated["sticky_target_enabled"] = bool(migrated["single_target_mode"])

    if "tracker_prediction_time" in migrated and "prediction_lead_time_s" not in migrated:
        migrated["prediction_lead_time_s"] = float(migrated["tracker_prediction_time"])

    if "tracker_smoothing_factor" in migrated and "velocity_ema_alpha" not in migrated:
        legacy_smoothing = _clamp(float(migrated["tracker_smoothing_factor"]), 0.0, 1.0)
        migrated["velocity_ema_alpha"] = _clamp(1.0 - legacy_smoothing, 0.0, 1.0)

    if "tracker_stop_threshold" in migrated and "velocity_deadzone_px_per_s" not in migrated:
        migrated["velocity_deadzone_px_per_s"] = float(migrated["tracker_stop_threshold"])

    controller_version = int(migrated.get("controller_version", 1) or 1)
    if controller_version < 2:
        nominal_dt = float(migrated.get("detect_interval", 0.02) or 0.02)
        nominal_dt = _clamp(nominal_dt, 0.001, 0.1)
        for axis in ("x", "y"):
            ki_key = f"pid_ki_{axis}"
            kd_key = f"pid_kd_{axis}"
            if ki_key in migrated:
                migrated[ki_key] = float(migrated[ki_key]) / nominal_dt
            if kd_key in migrated:
                migrated[kd_key] = float(migrated[kd_key]) * nominal_dt
        migrated["controller_version"] = 2

    return drop_legacy_config_keys(migrated)


class Config:
    def __init__(self) -> None:
        default_model = get_default_model_spec()

        self.width, self.height = _get_screen_size()
        self.center_x: int = self.width // 2
        self.center_y: int = self.height // 2

        self.capture_width: int = self.width
        self.capture_height: int = self.height
        self.capture_left: int = 0
        self.capture_top: int = 0
        self.crosshairX: int = self.width // 2
        self.crosshairY: int = self.height // 2
        self.region: Dict[str, int] = {
            "top": 0,
            "left": 0,
            "width": self.width,
            "height": self.height,
        }

        self.Running: bool = True
        self.AimToggle: bool = True

        self.model_id: str = default_model.model_id
        self.model_input_size: int = default_model.input_size
        self.model_path: str = default_model.engine_path
        self.current_provider: str = "Ultralytics/TensorRT"

        self.AimKeys: List[int] = [0x01, 0x06, 0x02]
        self.fov_size: int = 222
        self.detect_range_size: int = default_model.input_size
        self.show_confidence: bool = True
        self.min_confidence: float = 0.11
        self.aim_part: str = "head"
        self.active_target_class: str = default_model.labels[0]
        self.sticky_target_enabled: bool = True
        self.capture_backend: str = "auto"

        self.bezier_curve_enabled: bool = False
        self.bezier_curve_strength: float = 0.35
        self.bezier_curve_steps: int = 4

        self.tracker_enabled: bool = True
        self.prediction_lead_time_s: float = 0.05
        self.velocity_ema_alpha: float = 0.45
        self.velocity_deadzone_px_per_s: float = 10.0
        self.screen_motion_compensation_enabled: bool = True
        self.screen_motion_compensation_ratio: float = 1.0
        self.tracker_show_prediction: bool = True
        self.tracker_predicted_x: float = 0.0
        self.tracker_predicted_y: float = 0.0
        self.tracker_current_x: float = 0.0
        self.tracker_current_y: float = 0.0
        self.tracker_has_prediction: bool = False

        self.controller_version: int = 2
        self.aim_position_deadzone_px: float = 1.0
        self.lock_retain_radius_px: float = 48.0
        self.lock_retain_time_s: float = 0.12
        self.target_point_smoothing_alpha: float = 0.35
        self.prediction_max_distance_px: float = 40.0

        self.disclaimer_agreed: bool = False
        self.first_run_complete: bool = False

        self.head_width_ratio: float = 0.38
        self.head_height_ratio: float = 0.26
        self.body_width_ratio: float = 0.87

        self.pid_kp_x: float = 0.45
        self.pid_ki_x: float = 0.005
        self.pid_kd_x: float = 0.0
        self.pid_kp_y: float = 0.45
        self.pid_ki_y: float = 0.005
        self.pid_kd_y: float = 0.0

        self.mouse_move_method: str = "mouse_event"
        self.mouse_click_method: str = "mouse_event"
        self.arduino_com_port: str = ""

        self.xbox_sensitivity: float = 1.0
        self.xbox_deadzone: float = 0.05
        self.xbox_auto_connect: bool = True

        self.detect_interval: float = 0.005
        self.idle_detect_interval: float = 0.05
        self.aim_toggle_key: int = 45
        self.cycle_target_key: int = 0x77
        self.auto_fire_key2: int = 0x04

        self.auto_fire_key: int = 0x06
        self.always_auto_fire: bool = False
        self.auto_fire_delay: float = 0.0
        self.auto_fire_interval: float = 0.08
        self.auto_fire_target_part: str = "both"

        self.keep_detecting: bool = True
        self.always_aim: bool = False
        self.fov_follow_mouse: bool = True
        self.control_loop_hz: float = 500.0
        self.control_stale_hold_ms: float = 20.0
        self.control_stale_decay_ms: float = 40.0

        self.show_fov: bool = True
        self.show_boxes: bool = True
        self.show_detect_range: bool = False
        self.show_status_panel: bool = True
        self.show_console: bool = True

        self.dark_mode: bool = False
        self.enable_acrylic: bool = True
        self.acrylic_window_alpha: int = 187
        self.acrylic_element_alpha: int = 25

        self.performance_mode: bool = True
        self.max_queue_size: int = 1

        self.enable_latency_stats: bool = False
        self.latency_stats_interval: float = 1.0
        self.latency_stats_alpha: float = 0.2

        self.last_detection_time: float = 0.0
        self.last_overlay_update_time: float = 0.0
        self.runtime_refresh_token: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fov_size": self.fov_size,
            "detect_range_size": self.detect_range_size,
            "model_path": self.model_path,
            "model_id": self.model_id,
            "model_input_size": self.model_input_size,
            "current_provider": self.current_provider,
            "pid_kp_x": self.pid_kp_x,
            "pid_ki_x": self.pid_ki_x,
            "pid_kd_x": self.pid_kd_x,
            "pid_kp_y": self.pid_kp_y,
            "pid_ki_y": self.pid_ki_y,
            "pid_kd_y": self.pid_kd_y,
            "aim_part": self.aim_part,
            "active_target_class": self.active_target_class,
            "AimKeys": self.AimKeys,
            "auto_fire_key": self.auto_fire_key,
            "always_auto_fire": self.always_auto_fire,
            "auto_fire_delay": self.auto_fire_delay,
            "auto_fire_interval": self.auto_fire_interval,
            "auto_fire_target_part": self.auto_fire_target_part,
            "min_confidence": self.min_confidence,
            "show_confidence": self.show_confidence,
            "detect_interval": self.detect_interval,
            "idle_detect_interval": self.idle_detect_interval,
            "keep_detecting": self.keep_detecting,
            "always_aim": self.always_aim,
            "fov_follow_mouse": self.fov_follow_mouse,
            "control_loop_hz": self.control_loop_hz,
            "control_stale_hold_ms": self.control_stale_hold_ms,
            "control_stale_decay_ms": self.control_stale_decay_ms,
            "aim_toggle_key": self.aim_toggle_key,
            "cycle_target_key": self.cycle_target_key,
            "auto_fire_key2": self.auto_fire_key2,
            "AimToggle": self.AimToggle,
            "show_fov": self.show_fov,
            "show_boxes": self.show_boxes,
            "show_detect_range": self.show_detect_range,
            "show_status_panel": self.show_status_panel,
            "sticky_target_enabled": self.sticky_target_enabled,
            "capture_backend": self.capture_backend,
            "head_width_ratio": self.head_width_ratio,
            "head_height_ratio": self.head_height_ratio,
            "body_width_ratio": self.body_width_ratio,
            "performance_mode": self.performance_mode,
            "max_queue_size": self.max_queue_size,
            "enable_latency_stats": self.enable_latency_stats,
            "latency_stats_interval": self.latency_stats_interval,
            "latency_stats_alpha": self.latency_stats_alpha,
            "mouse_move_method": self.mouse_move_method,
            "mouse_click_method": self.mouse_click_method,
            "arduino_com_port": self.arduino_com_port,
            "xbox_sensitivity": self.xbox_sensitivity,
            "xbox_deadzone": self.xbox_deadzone,
            "xbox_auto_connect": self.xbox_auto_connect,
            "show_console": self.show_console,
            "bezier_curve_enabled": self.bezier_curve_enabled,
            "bezier_curve_strength": self.bezier_curve_strength,
            "bezier_curve_steps": self.bezier_curve_steps,
            "disclaimer_agreed": self.disclaimer_agreed,
            "first_run_complete": self.first_run_complete,
            "tracker_enabled": self.tracker_enabled,
            "prediction_lead_time_s": self.prediction_lead_time_s,
            "velocity_ema_alpha": self.velocity_ema_alpha,
            "velocity_deadzone_px_per_s": self.velocity_deadzone_px_per_s,
            "screen_motion_compensation_enabled": self.screen_motion_compensation_enabled,
            "screen_motion_compensation_ratio": self.screen_motion_compensation_ratio,
            "tracker_show_prediction": self.tracker_show_prediction,
            "dark_mode": self.dark_mode,
            "enable_acrylic": self.enable_acrylic,
            "acrylic_window_alpha": self.acrylic_window_alpha,
            "acrylic_element_alpha": self.acrylic_element_alpha,
            "controller_version": self.controller_version,
            "aim_position_deadzone_px": self.aim_position_deadzone_px,
            "lock_retain_radius_px": self.lock_retain_radius_px,
            "lock_retain_time_s": self.lock_retain_time_s,
            "target_point_smoothing_alpha": self.target_point_smoothing_alpha,
            "prediction_max_distance_px": self.prediction_max_distance_px,
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)


def save_config(config_instance: Config, filepath: str = "config.json") -> bool:
    try:
        existing_data: Dict[str, Any] = {}
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                existing_data = {}

        existing_data.update(config_instance.to_dict())
        existing_data = drop_legacy_config_keys(existing_data)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=2)
        print("Config saved successfully.")
        return True
    except OSError as e:
        print(f"Failed to save config (IO error): {e}")
        return False
    except (TypeError, ValueError) as e:
        print(f"Failed to save config (serialization error): {e}")
        return False


def load_config(config_instance: Config, filepath: str = "config.json") -> bool:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        migrated_data = migrate_config_data(data)
        config_instance.from_dict(migrated_data)
        _validate_detect_interval(config_instance)
        _validate_idle_detect_interval(config_instance)
        _validate_mouse_method(config_instance)
        _validate_capture_backend(config_instance)
        _validate_stability_settings(config_instance)
        _migrate_model_settings(config_instance)

        print("Config loaded successfully.")
        return True
    except FileNotFoundError:
        print("Config file not found, using defaults.")
        _migrate_model_settings(config_instance)
        return False
    except json.JSONDecodeError as e:
        print(f"Failed to load config (JSON format error): {e}")
        return False
    except OSError as e:
        print(f"Failed to load config (IO error): {e}")
        return False


def _validate_detect_interval(config: Config) -> None:
    detect_interval_ms = config.detect_interval * 1000
    if detect_interval_ms < 1:
        config.detect_interval = 0.001
        print("[Config Fix] Detection interval too small, adjusted to 1ms")
    elif detect_interval_ms > 100:
        config.detect_interval = 0.1
        print("[Config Fix] Detection interval too large, adjusted to 100ms")


def _validate_idle_detect_interval(config: Config) -> None:
    idle_ms = getattr(config, "idle_detect_interval", 0.05) * 1000
    if idle_ms < 5:
        config.idle_detect_interval = 0.005
        print("[Config Fix] Idle detection interval too small, adjusted to 5ms")
    elif idle_ms > 500:
        config.idle_detect_interval = 0.5
        print("[Config Fix] Idle detection interval too large, adjusted to 500ms")


def _validate_mouse_method(config: Config) -> None:
    if config.mouse_move_method == "hardware":
        config.mouse_move_method = "mouse_event"

    if config.mouse_move_method == "ddxoft" and config.mouse_click_method != "mouse_event":
        config.mouse_click_method = "mouse_event"


def _validate_capture_backend(config: Config) -> None:
    capture_backend = str(getattr(config, "capture_backend", "auto") or "auto").lower()
    if capture_backend == "mss":
        capture_backend = "dxcam"
    if capture_backend not in VALID_CAPTURE_BACKENDS:
        capture_backend = "auto"
    config.capture_backend = capture_backend


def bump_runtime_refresh_token(config: Config) -> int:
    config.runtime_refresh_token = int(getattr(config, "runtime_refresh_token", 0) or 0) + 1
    return config.runtime_refresh_token


def _resolve_model_spec(config: Config) -> ModelSpec:
    model_id = getattr(config, "model_id", "")
    if model_id:
        spec = get_model_spec(model_id)
        if spec is not None:
            return spec

    spec = resolve_model_spec_from_path(getattr(config, "model_path", ""))
    if spec is not None:
        return spec

    return get_default_model_spec()


def _validate_fov_size(config: Config, spec: ModelSpec | None = None) -> None:
    spec = spec or _resolve_model_spec(config)
    try:
        raw = int(getattr(config, "fov_size", 0) or 0)
    except (TypeError, ValueError):
        raw = 0

    max_size = min(int(getattr(config, "width", spec.input_size) or spec.input_size), int(getattr(config, "height", spec.input_size) or spec.input_size))
    if getattr(spec, "lock_detect_range_to_input", False):
        max_size = min(max_size, int(spec.input_size))
    if max_size <= 0:
        max_size = int(spec.input_size)
    min_size = 50 if max_size >= 50 else 1

    config.fov_size = max(min_size, min(max_size, raw if raw > 0 else int(spec.input_size)))


def _validate_detect_range_size(config: Config, spec: ModelSpec | None = None) -> None:
    spec = spec or _resolve_model_spec(config)
    if getattr(spec, "lock_detect_range_to_input", False):
        config.detect_range_size = int(spec.input_size)
        return

    try:
        raw = int(getattr(config, "detect_range_size", config.height))
    except (TypeError, ValueError):
        raw = int(config.height)

    min_size = int(getattr(config, "fov_size", 0) or 0)
    max_size = min(int(getattr(config, "width", raw) or raw), int(getattr(config, "height", raw) or raw))
    if max_size <= 0:
        max_size = raw if raw > 0 else 1

    config.detect_range_size = max(min_size, min(max_size, raw))


def _validate_stability_settings(config: Config) -> None:
    config.controller_version = max(2, int(getattr(config, "controller_version", 2) or 2))
    config.aim_position_deadzone_px = _clamp(float(getattr(config, "aim_position_deadzone_px", 3.0)), 0.0, 20.0)
    config.lock_retain_radius_px = _clamp(float(getattr(config, "lock_retain_radius_px", 48.0)), 8.0, float(config.width))
    config.lock_retain_time_s = _clamp(float(getattr(config, "lock_retain_time_s", 0.12)), 0.0, 1.0)
    config.target_point_smoothing_alpha = _clamp(float(getattr(config, "target_point_smoothing_alpha", 0.35)), 0.0, 1.0)
    config.screen_motion_compensation_enabled = bool(getattr(config, "screen_motion_compensation_enabled", True))
    config.prediction_lead_time_s = _clamp(float(getattr(config, "prediction_lead_time_s", 0.05)), 0.0, 0.1)
    config.velocity_ema_alpha = _clamp(float(getattr(config, "velocity_ema_alpha", 0.45)), 0.0, 1.0)
    config.velocity_deadzone_px_per_s = _clamp(float(getattr(config, "velocity_deadzone_px_per_s", 10.0)), 0.0, 500.0)
    config.screen_motion_compensation_ratio = _clamp(
        float(getattr(config, "screen_motion_compensation_ratio", 1.0)),
        0.0,
        1.5,
    )
    config.prediction_max_distance_px = _clamp(float(getattr(config, "prediction_max_distance_px", 40.0)), 0.0, 200.0)
    config.control_loop_hz = _clamp(float(getattr(config, "control_loop_hz", 500.0)), 30.0, 1000.0)
    config.control_stale_hold_ms = _clamp(float(getattr(config, "control_stale_hold_ms", 20.0)), 0.0, 250.0)
    config.control_stale_decay_ms = _clamp(float(getattr(config, "control_stale_decay_ms", 40.0)), 0.0, 500.0)


def _migrate_model_settings(config: Config) -> None:
    spec = _resolve_model_spec(config)
    config.model_id = spec.model_id
    config.model_path = spec.engine_path
    config.model_input_size = spec.input_size
    config.current_provider = "Ultralytics/TensorRT"

    if getattr(config, "active_target_class", "") not in spec.labels:
        config.active_target_class = spec.labels[0]

    _validate_fov_size(config, spec)
    _validate_detect_range_size(config, spec)


def apply_model_constraints(config: Config) -> None:
    _migrate_model_settings(config)

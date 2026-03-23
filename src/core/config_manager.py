"""Named config profile management."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .config import (
    drop_legacy_config_keys,
    migrate_config_data,
    _migrate_model_settings,
    _validate_capture_backend,
    _validate_detect_interval,
    _validate_idle_detect_interval,
    _validate_mouse_method,
    _validate_stability_settings,
)

if TYPE_CHECKING:
    from .config import Config


class ConfigManager:
    def __init__(self, configs_dir: str = "config") -> None:
        self.configs_dir = configs_dir
        self.ensure_configs_directory()

    def ensure_configs_directory(self) -> None:
        if not os.path.exists(self.configs_dir):
            os.makedirs(self.configs_dir)

    def get_config_list(self) -> List[str]:
        if not os.path.exists(self.configs_dir):
            return []

        configs = []
        for file in os.listdir(self.configs_dir):
            if file.endswith(".json"):
                configs.append(file[:-5])
        return sorted(configs)

    def save_config(self, config_instance: Config, config_name: str) -> bool:
        config_path = os.path.join(self.configs_dir, f"{config_name}.json")
        config_data = {
            "name": config_name,
            "created_time": datetime.now().isoformat(),
            "description": f"Parameter profile - {config_name}",
            "config": self._get_config_data(config_instance),
        }

        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            return True
        except OSError as e:
            print(f"Failed to save profile: {e}")
            return False

    def _get_config_data(self, config_instance: Config) -> Dict[str, Any]:
        return drop_legacy_config_keys(
            {
                "fov_size": config_instance.fov_size,
                "detect_range_size": getattr(config_instance, "detect_range_size", getattr(config_instance, "height", 0)),
                "min_confidence": config_instance.min_confidence,
                "detect_interval": config_instance.detect_interval,
                "idle_detect_interval": getattr(config_instance, "idle_detect_interval", 0.05),
                "model_path": config_instance.model_path,
                "model_id": getattr(config_instance, "model_id", ""),
                "model_input_size": config_instance.model_input_size,
                "current_provider": config_instance.current_provider,
                "capture_backend": getattr(config_instance, "capture_backend", "auto"),
                "pid_kp_x": config_instance.pid_kp_x,
                "pid_ki_x": config_instance.pid_ki_x,
                "pid_kd_x": config_instance.pid_kd_x,
                "pid_kp_y": config_instance.pid_kp_y,
                "pid_ki_y": config_instance.pid_ki_y,
                "pid_kd_y": config_instance.pid_kd_y,
                "aim_part": config_instance.aim_part,
                "active_target_class": getattr(config_instance, "active_target_class", ""),
                "sticky_target_enabled": getattr(config_instance, "sticky_target_enabled", True),
                "head_width_ratio": config_instance.head_width_ratio,
                "head_height_ratio": config_instance.head_height_ratio,
                "body_width_ratio": config_instance.body_width_ratio,
                "bezier_curve_enabled": getattr(config_instance, "bezier_curve_enabled", False),
                "bezier_curve_strength": getattr(config_instance, "bezier_curve_strength", 0.35),
                "bezier_curve_steps": getattr(config_instance, "bezier_curve_steps", 4),
                "AimKeys": config_instance.AimKeys,
                "aim_toggle_key": config_instance.aim_toggle_key,
                "cycle_target_key": getattr(config_instance, "cycle_target_key", 0x77),
                "auto_fire_key": config_instance.auto_fire_key,
                "auto_fire_key2": config_instance.auto_fire_key2,
                "always_auto_fire": getattr(config_instance, "always_auto_fire", False),
                "auto_fire_delay": config_instance.auto_fire_delay,
                "auto_fire_interval": config_instance.auto_fire_interval,
                "auto_fire_target_part": config_instance.auto_fire_target_part,
                "show_confidence": config_instance.show_confidence,
                "show_fov": config_instance.show_fov,
                "show_boxes": config_instance.show_boxes,
                "show_detect_range": getattr(config_instance, "show_detect_range", False),
                "show_status_panel": config_instance.show_status_panel,
                "show_console": config_instance.show_console,
                "AimToggle": config_instance.AimToggle,
                "keep_detecting": config_instance.keep_detecting,
                "always_aim": getattr(config_instance, "always_aim", False),
                "fov_follow_mouse": config_instance.fov_follow_mouse,
                "performance_mode": config_instance.performance_mode,
                "max_queue_size": config_instance.max_queue_size,
                "mouse_move_method": getattr(config_instance, "mouse_move_method", "mouse_event"),
                "mouse_click_method": getattr(config_instance, "mouse_click_method", "mouse_event"),
                "arduino_com_port": getattr(config_instance, "arduino_com_port", ""),
                "xbox_sensitivity": getattr(config_instance, "xbox_sensitivity", 1.0),
                "xbox_deadzone": getattr(config_instance, "xbox_deadzone", 0.05),
                "xbox_auto_connect": getattr(config_instance, "xbox_auto_connect", True),
                "tracker_enabled": getattr(config_instance, "tracker_enabled", True),
                "prediction_lead_time_s": getattr(config_instance, "prediction_lead_time_s", 0.018),
                "velocity_ema_alpha": getattr(config_instance, "velocity_ema_alpha", 0.45),
                "velocity_deadzone_px_per_s": getattr(config_instance, "velocity_deadzone_px_per_s", 10.0),
                "screen_motion_compensation_enabled": getattr(
                    config_instance,
                    "screen_motion_compensation_enabled",
                    True,
                ),
                "screen_motion_compensation_ratio": getattr(
                    config_instance,
                    "screen_motion_compensation_ratio",
                    1.0,
                ),
                "tracker_show_prediction": getattr(config_instance, "tracker_show_prediction", True),
                "enable_latency_stats": getattr(config_instance, "enable_latency_stats", False),
                "latency_stats_interval": getattr(config_instance, "latency_stats_interval", 1.0),
                "latency_stats_alpha": getattr(config_instance, "latency_stats_alpha", 0.2),
                "controller_version": getattr(config_instance, "controller_version", 2),
                "aim_position_deadzone_px": getattr(config_instance, "aim_position_deadzone_px", 3.0),
                "lock_retain_radius_px": getattr(config_instance, "lock_retain_radius_px", 48.0),
                "lock_retain_time_s": getattr(config_instance, "lock_retain_time_s", 0.12),
                "target_point_smoothing_alpha": getattr(config_instance, "target_point_smoothing_alpha", 0.35),
                "prediction_max_distance_px": getattr(config_instance, "prediction_max_distance_px", 20.0),
                "control_stale_hold_ms": getattr(config_instance, "control_stale_hold_ms", 12.0),
                "control_stale_decay_ms": getattr(config_instance, "control_stale_decay_ms", 24.0),
            }
        )

    def load_config(self, config_instance: Config, config_name: str) -> bool:
        config_path = os.path.join(self.configs_dir, f"{config_name}.json")
        if not os.path.exists(config_path):
            return False

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)

            migrated = migrate_config_data(config_data.get("config", {}))
            for key, value in migrated.items():
                if hasattr(config_instance, key):
                    setattr(config_instance, key, value)
            _validate_detect_interval(config_instance)
            _validate_idle_detect_interval(config_instance)
            _validate_mouse_method(config_instance)
            _validate_capture_backend(config_instance)
            _validate_stability_settings(config_instance)
            _migrate_model_settings(config_instance)
            return True
        except (OSError, json.JSONDecodeError) as e:
            print(f"Failed to load profile: {e}")
            return False

    def delete_config(self, config_name: str) -> bool:
        config_path = os.path.join(self.configs_dir, f"{config_name}.json")
        if not os.path.exists(config_path):
            return False

        try:
            os.remove(config_path)
            return True
        except OSError as e:
            print(f"Failed to delete profile: {e}")
            return False

    def rename_config(self, old_name: str, new_name: str) -> bool:
        old_path = os.path.join(self.configs_dir, f"{old_name}.json")
        new_path = os.path.join(self.configs_dir, f"{new_name}.json")

        if not os.path.exists(old_path) or os.path.exists(new_path):
            return False

        try:
            with open(old_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
            config_data["name"] = new_name

            with open(new_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)

            os.remove(old_path)
            return True
        except (OSError, json.JSONDecodeError) as e:
            print(f"Failed to rename profile: {e}")
            return False

    def export_config(self, config_name: str, export_path: str) -> bool:
        config_path = os.path.join(self.configs_dir, f"{config_name}.json")
        if not os.path.exists(config_path):
            return False

        try:
            shutil.copy2(config_path, export_path)
            return True
        except OSError as e:
            print(f"Failed to export profile: {e}")
            return False

    def import_config(self, import_path: str) -> Optional[str]:
        if not os.path.exists(import_path):
            return None

        try:
            with open(import_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)

            config_name = config_data.get("name", "imported_config")
            original_name = config_name
            counter = 1
            while os.path.exists(os.path.join(self.configs_dir, f"{config_name}.json")):
                config_name = f"{original_name}_{counter}"
                counter += 1

            config_data["name"] = config_name
            config_path = os.path.join(self.configs_dir, f"{config_name}.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)

            return config_name
        except (OSError, json.JSONDecodeError) as e:
            print(f"Failed to import profile: {e}")
            return None

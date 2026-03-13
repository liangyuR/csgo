"""Configuration loading for real-time aim mode.

Reads a YAML file and exposes typed dataclass objects for each section.
Falls back to built-in defaults when keys are absent so the config file
can be partially specified.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ------------------------------------------------------------------
# Section dataclasses
# ------------------------------------------------------------------

@dataclass
class CaptureSection:
    method: str = "mss"
    region: str = "full"          # "full" | "center_crop"
    center_crop_size: int = 640
    monitor_index: int = 1


@dataclass
class ModelSection:
    path: str = "model/best.pt"
    confidence: float = 0.35
    imgsz: int = 640
    device: Optional[str] = None
    target_class_names: List[str] = field(default_factory=list)
    target_class_ids: List[int] = field(default_factory=list)


@dataclass
class AimSection:
    mode: str = "pose_head"       # "center" | "upper_center" | "pose_head"
    target_strategy: str = "nearest_head_to_center"
    min_keypoint_confidence: float = 0.35
    head_fraction: float = 0.18
    fov_radius: float = 200.0
    smoothing: float = 0.4
    sensitivity: float = 1.0
    deadzone_pixels: float = 3.0  # stop moving when crosshair is this close
    max_speed: float = 30.0       # max mouse delta magnitude per tick (pixels)


@dataclass
class HotkeySection:
    toggle: str = "f2"
    exit: str = "f10"
    mode: str = "hold"            # "toggle" | "hold"


@dataclass
class DebugSection:
    enabled: bool = True
    window_width: int = 360
    window_height: int = 200
    top_right_margin: int = 24
    refresh_ms: int = 150
    perf_log_interval_sec: float = 5.0
    save_frames: bool = True
    save_interval_sec: float = 5.0
    output_dir: str = "outputs/realtime_debug"


@dataclass
class RuntimeSection:
    log_interval_sec: float = 5.0
    warmup_frames: int = 1
    max_stale_frame_ms: float = 500.0
    capture_sleep_ms: float = 1.0


@dataclass
class RealtimeConfig:
    capture: CaptureSection = field(default_factory=CaptureSection)
    model: ModelSection = field(default_factory=ModelSection)
    aim: AimSection = field(default_factory=AimSection)
    hotkeys: HotkeySection = field(default_factory=HotkeySection)
    debug: DebugSection = field(default_factory=DebugSection)
    runtime: RuntimeSection = field(default_factory=RuntimeSection)


# ------------------------------------------------------------------
# Loader
# ------------------------------------------------------------------

def load_config(path: str | Path | None = None) -> RealtimeConfig:
    """Load a YAML config file and return a RealtimeConfig.

    If *path* is None the function looks for ``config.yaml`` in the current
    working directory.  If that file does not exist, built-in defaults are
    returned silently.
    """
    if path is None:
        candidate = Path("config.yaml")
        if not candidate.exists():
            return RealtimeConfig()
        path = candidate

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "pyyaml is not installed. Run: pip install pyyaml"
        ) from exc

    with path.open(encoding="utf-8") as fh:
        data: dict = yaml.safe_load(fh) or {}

    return _build_config(data)


def _build_config(data: dict) -> RealtimeConfig:
    cap_raw = data.get("capture", {}) or {}
    model_raw = data.get("model", {}) or {}
    aim_raw = data.get("aim", {}) or {}
    hk_raw = data.get("hotkeys", {}) or {}
    debug_raw = data.get("debug", {}) or {}
    runtime_raw = data.get("runtime", {}) or {}

    capture = CaptureSection(
        method=cap_raw.get("method", "mss"),
        region=cap_raw.get("region", "full"),
        center_crop_size=int(cap_raw.get("center_crop_size", 640)),
        monitor_index=int(cap_raw.get("monitor_index", 1)),
    )

    model = ModelSection(
        path=str(model_raw.get("path", "model/best.pt")),
        confidence=float(model_raw.get("confidence", 0.35)),
        imgsz=int(model_raw.get("imgsz", 640)),
        device=model_raw.get("device", None),
        target_class_names=list(model_raw.get("target_class_names") or []),
        target_class_ids=[int(x) for x in (model_raw.get("target_class_ids") or [])],
    )

    aim = AimSection(
        mode=str(aim_raw.get("mode", "pose_head")),
        target_strategy=str(aim_raw.get("target_strategy", "nearest_head_to_center")),
        min_keypoint_confidence=float(aim_raw.get("min_keypoint_confidence", 0.35)),
        head_fraction=float(aim_raw.get("head_fraction", 0.18)),
        fov_radius=float(aim_raw.get("fov_radius", 200.0)),
        smoothing=float(aim_raw.get("smoothing", 0.4)),
        sensitivity=float(aim_raw.get("sensitivity", 1.0)),
        deadzone_pixels=float(aim_raw.get("deadzone_pixels", 3.0)),
        max_speed=float(aim_raw.get("max_speed", 30.0)),
    )

    hotkeys = HotkeySection(
        toggle=str(hk_raw.get("toggle", "f2")),
        exit=str(hk_raw.get("exit", "f10")),
        mode=str(hk_raw.get("mode", "hold")),
    )

    debug = DebugSection(
        enabled=bool(debug_raw.get("enabled", True)),
        window_width=int(debug_raw.get("window_width", 360)),
        window_height=int(debug_raw.get("window_height", 200)),
        top_right_margin=int(debug_raw.get("top_right_margin", 24)),
        refresh_ms=int(debug_raw.get("refresh_ms", 150)),
        perf_log_interval_sec=float(debug_raw.get("perf_log_interval_sec", 5.0)),
        save_frames=bool(debug_raw.get("save_frames", True)),
        save_interval_sec=float(debug_raw.get("save_interval_sec", 5.0)),
        output_dir=str(debug_raw.get("output_dir", "outputs/realtime_debug")),
    )
    runtime = RuntimeSection(
        log_interval_sec=float(runtime_raw.get("log_interval_sec", 5.0)),
        warmup_frames=int(runtime_raw.get("warmup_frames", 1)),
        max_stale_frame_ms=float(runtime_raw.get("max_stale_frame_ms", 500.0)),
        capture_sleep_ms=float(runtime_raw.get("capture_sleep_ms", 1.0)),
    )

    return RealtimeConfig(
        capture=capture,
        model=model,
        aim=aim,
        hotkeys=hotkeys,
        debug=debug,
        runtime=runtime,
    )

"""Real-time main loop.

Architecture
------------
A producer thread continuously grabs frames from the screen into a
single-element "latest frame" slot.  The main thread reads that slot,
runs YOLO inference, applies smoothing, and moves the mouse.

Using a dedicated capture thread means the inference loop never blocks
waiting for a screenshot; it always works on the freshest available frame.

Usage
-----
    from csgo_vision_demo.config import load_config
    from csgo_vision_demo.realtime import run_realtime

    cfg = load_config("config.yaml")
    run_realtime(cfg)
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from .capture import CaptureConfig, ScreenCapture
from .config import RealtimeConfig
from .geometry import build_detection_geometry, select_primary_index
from .hotkey import HotkeyManager
from .mouse import MouseController
from .pipeline import OfflineAimAnalyzer
from .smoother import AimSmoother


# ------------------------------------------------------------------
# Capture thread
# ------------------------------------------------------------------

class _FrameBuffer:
    """Thread-safe single-slot frame buffer (keeps only the latest frame)."""

    def __init__(self) -> None:
        self._frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()

    def put(self, frame: np.ndarray) -> None:
        with self._lock:
            self._frame = frame

    def get(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._frame


class _CaptureThread(threading.Thread):
    def __init__(self, capture: ScreenCapture, buf: _FrameBuffer) -> None:
        super().__init__(daemon=True, name="capture-thread")
        self._capture = capture
        self._buf = buf
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                frame = self._capture.grab()
                self._buf.put(frame)
            except Exception:
                pass


# ------------------------------------------------------------------
# Main realtime runner
# ------------------------------------------------------------------

def run_realtime(cfg: RealtimeConfig) -> None:
    """Start the real-time aim loop.  Blocks until the exit hotkey is pressed.

    Steps each iteration:
        1. Read latest frame from capture thread
        2. Run YOLO inference via OfflineAimAnalyzer.analyze_frame()
        3. Select primary target (closest to capture-region centre)
        4. Apply FOV gate + lerp smoothing
        5. Send relative mouse movement via SendInput
    """
    # ---- build subsystems ----------------------------------------

    cap_cfg = CaptureConfig(
        method=cfg.capture.method,
        region=cfg.capture.region,
        center_crop_size=cfg.capture.center_crop_size,
        monitor_index=cfg.capture.monitor_index,
    )
    capture = ScreenCapture(cap_cfg)

    analyzer = OfflineAimAnalyzer(
        model_path=cfg.model.path,
        confidence=cfg.model.confidence,
        imgsz=cfg.model.imgsz,
        device=cfg.model.device,
        target_class_names=cfg.model.target_class_names,
        target_class_ids=cfg.model.target_class_ids,
        aim_mode=cfg.aim.mode,
        head_fraction=cfg.aim.head_fraction,
    )

    smoother = AimSmoother(
        fov_radius=cfg.aim.fov_radius,
        smoothing=cfg.aim.smoothing,
    )

    mouse = MouseController(sensitivity=cfg.aim.sensitivity)

    hotkeys = HotkeyManager(
        toggle_key=cfg.hotkeys.toggle,
        exit_key=cfg.hotkeys.exit,
        mode=cfg.hotkeys.mode,
    )

    # ---- warm up model -------------------------------------------
    print("[realtime] Loading model...")
    _ = analyzer.model          # triggers lazy load
    print(f"[realtime] Model loaded: {cfg.model.path}")
    print(f"[realtime] Hotkeys -- toggle aim: {cfg.hotkeys.toggle} | exit: {cfg.hotkeys.exit}")

    # ---- start capture thread ------------------------------------
    buf = _FrameBuffer()
    capture.open()
    cap_thread = _CaptureThread(capture, buf)
    cap_thread.start()

    # ---- start hotkey listener -----------------------------------
    hotkeys.start()

    print("[realtime] Running. Press the toggle key to enable aiming.")
    print(f"[realtime] Capture region: {cap_cfg.region}  ({capture.width}x{capture.height})")

    # ---- main loop -----------------------------------------------
    frame_count = 0
    t_start = time.perf_counter()

    try:
        while hotkeys.running:
            frame = buf.get()
            if frame is None:
                time.sleep(0.001)
                continue

            detections, primary_index = analyzer.analyze_frame(frame)
            frame_count += 1

            if hotkeys.aim_active and primary_index is not None:
                det = detections[primary_index]
                move = smoother.compute(det.offset_x, det.offset_y)
                if move is not None:
                    mouse.move(move[0], move[1])
            else:
                smoother.reset()

            # Print FPS every 5 seconds
            elapsed = time.perf_counter() - t_start
            if elapsed >= 5.0:
                fps = frame_count / elapsed
                aim_str = "ON" if hotkeys.aim_active else "OFF"
                det_count = len(detections)
                print(
                    f"[realtime] FPS: {fps:.1f}  aim: {aim_str}  "
                    f"detections: {det_count}"
                )
                frame_count = 0
                t_start = time.perf_counter()

    except KeyboardInterrupt:
        print("[realtime] Interrupted by keyboard.")
    finally:
        cap_thread.stop()
        cap_thread.join(timeout=2.0)
        capture.close()
        hotkeys.stop()
        print("[realtime] Stopped.")

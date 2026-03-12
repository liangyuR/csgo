"""Real-time main loop."""
from __future__ import annotations

import time

from .config import RealtimeConfig
from .debug_overlay import DebugOverlay, debug_state_from_snapshot
from .hotkey import HotkeyManager
from .mouse import MouseController
from .realtime_engine import DetectionEngine
from .smoother import AimSmoother


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
    engine = DetectionEngine(cfg)

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
    debug_overlay = DebugOverlay(cfg.debug)

    print("[realtime] Starting detection engine...")
    engine.start()
    print(f"[realtime] Model loaded: {cfg.model.path}")
    print(f"[realtime] Hotkeys -- toggle aim: {cfg.hotkeys.toggle} | exit: {cfg.hotkeys.exit}")

    hotkeys.start()
    debug_overlay.start()

    print("[realtime] Running. Press the toggle key to enable aiming.")
    print(f"[realtime] Capture region: {cfg.capture.region}  ({engine.capture_width}x{engine.capture_height})")

    frame_count = 0
    t_start = time.perf_counter()
    last_status_reason = ""
    last_status_at = 0.0
    last_fps = 0.0
    perf_started = time.perf_counter()
    perf_frames = 0
    perf_inference_ms = 0.0
    perf_overlay_ms = 0.0
    perf_overlay_updates = 0
    perf_loop_ms = 0.0
    perf_interval = max(1.0, float(cfg.runtime.log_interval_sec))

    try:
        while hotkeys.running:
            loop_started = time.perf_counter()
            snapshot = engine.poll()
            perf_inference_ms += snapshot.inference_ms
            frame_count += 1
            perf_frames += 1
            move = None
            action_summary = "idle"
            det = snapshot.primary_target

            if hotkeys.aim_active and det is not None and snapshot.status == "running":
                move = smoother.compute(det.offset_x, det.offset_y)
                if move is not None:
                    mouse.move(move[0], move[1])
                    reason = (
                        f"aim ON target={det.class_name} source={det.aim_source} "
                        f"offset=({det.offset_x:.1f}, {det.offset_y:.1f}) move=({move[0]:.1f}, {move[1]:.1f})"
                    )
                    action_summary = f"move ({move[0]:.1f}, {move[1]:.1f})"
                else:
                    reason = (
                        f"aim ON target={det.class_name} source={det.aim_source} "
                        f"but smoother blocked move"
                    )
                    action_summary = "blocked by smoother"
            else:
                smoother.reset()
                if not hotkeys.aim_active:
                    reason = "aim OFF"
                    action_summary = "aim disabled"
                elif det is None:
                    reason = f"aim ON but no target detected (detections={len(snapshot.detections)})"
                    action_summary = "no target"
                elif snapshot.status != "running":
                    reason = f"engine {snapshot.status}: {snapshot.error or snapshot.reason}"
                    action_summary = snapshot.reason
                else:
                    reason = "aim ON but no movement"
                    action_summary = "no movement"

            overlay_updated, overlay_elapsed_ms = debug_overlay.update(
                snapshot,
                debug_state_from_snapshot(snapshot, last_fps, hotkeys.aim_active, action_summary),
            )
            if overlay_updated:
                perf_overlay_updates += 1
                perf_overlay_ms += overlay_elapsed_ms

            now = time.perf_counter()
            if reason != last_status_reason or (now - last_status_at) >= 2.0:
                print(f"[realtime] Status: {reason}")
                last_status_reason = reason
                last_status_at = now

            # Print FPS every 5 seconds
            elapsed = time.perf_counter() - t_start
            if elapsed >= 5.0:
                fps = frame_count / elapsed
                last_fps = fps
                aim_str = "ON" if hotkeys.aim_active else "OFF"
                det_count = len(snapshot.detections)
                print(
                    f"[realtime] FPS: {fps:.1f}  aim: {aim_str}  "
                    f"detections: {det_count}  engine: {snapshot.status}"
                )
                frame_count = 0
                t_start = time.perf_counter()

            perf_loop_ms += (time.perf_counter() - loop_started) * 1000.0
            perf_elapsed = time.perf_counter() - perf_started
            if perf_elapsed >= perf_interval and perf_frames > 0:
                avg_inference = perf_inference_ms / perf_frames
                avg_loop = perf_loop_ms / perf_frames
                avg_overlay = perf_overlay_ms / perf_overlay_updates if perf_overlay_updates else 0.0
                print(
                    "[realtime] Perf: "
                    f"frames={perf_frames} "
                    f"inference={avg_inference:.1f}ms "
                    f"loop={avg_loop:.1f}ms "
                    f"overlay={avg_overlay:.1f}ms "
                    f"overlay_updates={perf_overlay_updates} "
                    f"engine={snapshot.status} "
                    f"reason={snapshot.reason}"
                )
                perf_started = time.perf_counter()
                perf_frames = 0
                perf_inference_ms = 0.0
                perf_overlay_ms = 0.0
                perf_overlay_updates = 0
                perf_loop_ms = 0.0

    except KeyboardInterrupt:
        print("[realtime] Interrupted by keyboard.")
    finally:
        engine.stop()
        hotkeys.stop()
        debug_overlay.stop()
        print("[realtime] Stopped.")

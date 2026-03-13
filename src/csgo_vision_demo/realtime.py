"""Real-time main loop with aim-state machine and cross-frame target locking."""
from __future__ import annotations

import time
from enum import Enum
from math import sqrt
from typing import Optional

from .config import RealtimeConfig
from .debug_overlay import DebugOverlay, debug_state_from_snapshot
from .hotkey import HotkeyManager
from .mouse import MouseController
from .realtime_engine import DetectionEngine, DetectionRecord
from .smoother import AimSmoother


# ---------------------------------------------------------------------------
# Aim state machine
# ---------------------------------------------------------------------------

class AimState(Enum):
    """Three-state aim machine.

    IDLE   — hotkey is not held, or no valid target is within the FOV gate.
    AIMING — actively moving the mouse toward the locked target this tick.
    LOCKED — crosshair is within the deadzone; target acquired, no movement sent.
    """
    IDLE   = "idle"
    AIMING = "aiming"
    LOCKED = "locked"


# ---------------------------------------------------------------------------
# Target locking helper
# ---------------------------------------------------------------------------

# When searching for the same target across frames we match by bbox centre
# proximity.  This threshold (pixels) controls how much a target's centre
# can move between frames before we consider it a different person.
_LOCK_SEARCH_RADIUS_PX: float = 120.0


def _find_locked_target_index(
    detections: list[DetectionRecord],
    locked_cx: float,
    locked_cy: float,
    search_radius: float = _LOCK_SEARCH_RADIUS_PX,
) -> Optional[int]:
    """Return the index of the detection whose bbox centre is closest to
    (*locked_cx*, *locked_cy*), provided it lies within *search_radius*.

    Returns None when no detection is close enough — the caller should
    release the lock and fall back to the nearest-to-centre selection.
    """
    best_idx: Optional[int] = None
    best_dist = search_radius
    for i, det in enumerate(detections):
        cx = (det.x1 + det.x2) * 0.5
        cy = (det.y1 + det.y2) * 0.5
        dist = sqrt((cx - locked_cx) ** 2 + (cy - locked_cy) ** 2)
        if dist < best_dist:
            best_dist = dist
            best_idx = i
    return best_idx


# ---------------------------------------------------------------------------
# Main realtime runner
# ---------------------------------------------------------------------------

def run_realtime(cfg: RealtimeConfig) -> None:
    """Start the real-time aim loop.  Blocks until the exit hotkey is pressed.

    Loop per iteration:
      1. Poll the latest YOLO snapshot from the capture/inference thread.
      2. If hotkey is active: find the locked target (or lock on to the
         nearest-to-centre target for the first time).
      3. Compute smoothed mouse delta via AimSmoother (FOV gate → deadzone
         → lerp → max-speed clamp).
      4. Advance the AimState machine:
           IDLE   — no hotkey / no target / outside FOV gate
           AIMING — delta is non-zero, mouse movement sent via SendInput
           LOCKED — delta is (0, 0), crosshair already on target
      5. Update the debug overlay and console log.
    """
    engine = DetectionEngine(cfg)

    smoother = AimSmoother(
        fov_radius=cfg.aim.fov_radius,
        smoothing=cfg.aim.smoothing,
        deadzone_pixels=cfg.aim.deadzone_pixels,
        max_speed=cfg.aim.max_speed,
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
    print(f"[realtime] Model loaded:    {cfg.model.path}")
    print(f"[realtime] Aim mode:        {cfg.aim.mode}  fov={cfg.aim.fov_radius}px  "
          f"dead={cfg.aim.deadzone_pixels}px  max_speed={cfg.aim.max_speed}px/tick")
    print(f"[realtime] Hotkeys:         aim={cfg.hotkeys.toggle} ({cfg.hotkeys.mode})  "
          f"exit={cfg.hotkeys.exit}")

    hotkeys.start()
    debug_overlay.start()

    print("[realtime] Running.  Press the toggle key to enable aiming.")
    print(f"[realtime] Capture region: {cfg.capture.region}  "
          f"({engine.capture_width}x{engine.capture_height})")

    # --- Perf counters ---
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

    # --- Target lock state (maintained across frames) ---
    locked_cx: Optional[float] = None
    locked_cy: Optional[float] = None

    try:
        while hotkeys.running:
            loop_started = time.perf_counter()
            snapshot = engine.poll()
            perf_inference_ms += snapshot.inference_ms
            frame_count += 1
            perf_frames += 1

            move: Optional[tuple[int, int]] = None
            det: Optional[DetectionRecord] = None
            aim_state = AimState.IDLE

            # ----------------------------------------------------------
            # Aim logic
            # ----------------------------------------------------------
            if hotkeys.aim_active and snapshot.status == "running":

                # 1. Try to re-acquire the previously locked target by bbox
                #    centre proximity (keeps the crosshair on the same person
                #    even when another target becomes "nearer to centre").
                if locked_cx is not None and locked_cy is not None and snapshot.detections:
                    lock_idx = _find_locked_target_index(
                        snapshot.detections, locked_cx, locked_cy
                    )
                    if lock_idx is not None:
                        det = snapshot.detections[lock_idx]

                # 2. Fall back to the nearest-to-centre primary target when
                #    the lock is lost or this is the first frame.
                if det is None:
                    det = snapshot.primary_target

                if det is not None:
                    # Update the lock to follow the target as it moves.
                    locked_cx = (det.x1 + det.x2) * 0.5
                    locked_cy = (det.y1 + det.y2) * 0.5

                    move = smoother.compute(det.offset_x, det.offset_y)

                    if move is None:
                        # Outside FOV gate — release lock, go IDLE.
                        locked_cx = None
                        locked_cy = None
                        aim_state = AimState.IDLE
                    elif move[0] != 0 or move[1] != 0:
                        mouse.move(move[0], move[1])
                        aim_state = AimState.AIMING
                    else:
                        # Inside deadzone — acquired, no movement needed.
                        aim_state = AimState.LOCKED
                else:
                    # No detection at all — release lock.
                    locked_cx = None
                    locked_cy = None
                    smoother.reset()

            else:
                # Hotkey released or engine not running — full reset.
                locked_cx = None
                locked_cy = None
                smoother.reset()

            # ----------------------------------------------------------
            # Build human-readable summaries
            # ----------------------------------------------------------
            if aim_state == AimState.AIMING and det is not None and move is not None:
                action_summary = f"aiming ({move[0]:+d},{move[1]:+d})"
                reason = (
                    f"AIMING  target={det.class_name} src={det.aim_source} "
                    f"offset=({det.offset_x:.1f},{det.offset_y:.1f}) "
                    f"move=({move[0]:+d},{move[1]:+d})"
                )
            elif aim_state == AimState.LOCKED and det is not None:
                action_summary = "locked"
                reason = (
                    f"LOCKED  target={det.class_name} src={det.aim_source} "
                    f"offset=({det.offset_x:.1f},{det.offset_y:.1f})  "
                    f"[within deadzone {cfg.aim.deadzone_pixels}px]"
                )
            elif not hotkeys.aim_active:
                action_summary = "aim disabled"
                reason = "aim OFF"
            elif snapshot.status != "running":
                action_summary = snapshot.reason or snapshot.status
                reason = f"engine {snapshot.status}: {snapshot.error or snapshot.reason}"
            elif det is None:
                action_summary = "no target"
                reason = f"aim ON but no target  (detections={len(snapshot.detections)})"
            else:
                action_summary = "outside FOV"
                reason = (
                    f"aim ON but target outside FOV gate "
                    f"(dist > {cfg.aim.fov_radius:.0f}px)"
                )

            # ----------------------------------------------------------
            # Debug overlay
            # ----------------------------------------------------------
            overlay_updated, overlay_elapsed_ms = debug_overlay.update(
                snapshot,
                debug_state_from_snapshot(
                    snapshot, last_fps, hotkeys.aim_active, action_summary
                ),
            )
            if overlay_updated:
                perf_overlay_updates += 1
                perf_overlay_ms += overlay_elapsed_ms

            # ----------------------------------------------------------
            # Console log (rate-limited)
            # ----------------------------------------------------------
            now = time.perf_counter()
            if reason != last_status_reason or (now - last_status_at) >= 2.0:
                print(f"[realtime] {reason}")
                last_status_reason = reason
                last_status_at = now

            elapsed = time.perf_counter() - t_start
            if elapsed >= 5.0:
                fps = frame_count / elapsed
                last_fps = fps
                aim_str = "ON" if hotkeys.aim_active else "OFF"
                print(
                    f"[realtime] FPS={fps:.1f}  aim={aim_str}  "
                    f"state={aim_state.value}  "
                    f"detections={len(snapshot.detections)}  "
                    f"engine={snapshot.status}"
                )
                frame_count = 0
                t_start = time.perf_counter()

            # ----------------------------------------------------------
            # Perf logging
            # ----------------------------------------------------------
            perf_loop_ms += (time.perf_counter() - loop_started) * 1000.0
            perf_elapsed = time.perf_counter() - perf_started
            if perf_elapsed >= perf_interval and perf_frames > 0:
                avg_inference = perf_inference_ms / perf_frames
                avg_loop = perf_loop_ms / perf_frames
                avg_overlay = (
                    perf_overlay_ms / perf_overlay_updates
                    if perf_overlay_updates else 0.0
                )
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

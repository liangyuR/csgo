from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import time

import cv2
import numpy as np

from .config import DebugSection
from .realtime_engine import DetectionSnapshot


@dataclass(frozen=True)
class RealtimeDebugState:
    engine_status: str
    fps: float
    aim_active: bool
    detections: int
    primary_summary: str
    action_summary: str
    inference_ms: float
    error: str | None


def build_debug_lines(state: RealtimeDebugState) -> list[str]:
    aim_str = "ON" if state.aim_active else "OFF"
    # Derive a concise state label from the action_summary for prominent display.
    action_lower = state.action_summary.lower()
    if "locked" in action_lower:
        state_label = "LOCKED"
    elif "aiming" in action_lower:
        state_label = "AIMING"
    elif "disabled" in action_lower or aim_str == "OFF":
        state_label = "IDLE"
    else:
        state_label = state.action_summary.upper()[:10]

    return [
        "Realtime Debug",
        f"Engine: {state.engine_status}",
        f"FPS: {state.fps:.1f}",
        f"Aim: {aim_str}  [{state_label}]",
        f"Detections: {state.detections}",
        f"Infer: {state.inference_ms:.1f} ms",
        f"Target: {state.primary_summary}",
        f"Action: {state.action_summary}",
        f"Error: {state.error or '-'}",
    ]


def debug_state_from_snapshot(snapshot: DetectionSnapshot, fps: float, aim_active: bool, action_summary: str) -> RealtimeDebugState:
    primary = snapshot.primary_target
    if primary is None:
        primary_summary = "No target"
    else:
        primary_summary = (
            f"{primary.class_name} {primary.confidence:.2f} "
            f"{primary.aim_source} dx={primary.offset_x:.0f} dy={primary.offset_y:.0f}"
        )
    return RealtimeDebugState(
        engine_status=snapshot.status,
        fps=fps,
        aim_active=aim_active,
        detections=len(snapshot.detections),
        primary_summary=primary_summary,
        action_summary=action_summary,
        inference_ms=snapshot.inference_ms,
        error=snapshot.error,
    )


class DebugOverlay:
    def __init__(self, cfg: DebugSection, title: str = "CSGO Realtime Debug") -> None:
        self.cfg = cfg
        self.title = title
        self._enabled = bool(cfg.enabled)
        self._available = False
        self._last_update_at = 0.0
        self._last_saved_at = 0.0
        self._first_frame_logged = False
        self._save_dir = Path(self.cfg.output_dir)

    @property
    def active(self) -> bool:
        return self._enabled and self._available

    def start(self) -> None:
        if not self._enabled:
            return
        try:
            if self.cfg.save_frames:
                self._save_dir.mkdir(parents=True, exist_ok=True)
            cv2.namedWindow(self.title, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.title, self.cfg.window_width, self.cfg.window_height)
            cv2.setWindowProperty(self.title, cv2.WND_PROP_TOPMOST, 1)
            x, y = self._compute_window_origin()
            cv2.moveWindow(self.title, x, y)
            self._available = True
            print(f"[debug] Overlay enabled at ({x}, {y}).")
        except Exception as exc:
            self._available = False
            print(f"[debug] Overlay disabled: {exc}")

    def update(self, snapshot: DetectionSnapshot, state: RealtimeDebugState) -> tuple[bool, float]:
        if not self.active:
            return False, 0.0
        now = time.perf_counter()
        refresh_interval = max(0.0, float(self.cfg.refresh_ms) / 1000.0)
        if self._last_update_at and (now - self._last_update_at) < refresh_interval:
            return False, 0.0
        started = time.perf_counter()
        try:
            canvas = self._render_preview(snapshot, state)
            self._maybe_save_debug_images(snapshot, canvas, now)
            cv2.imshow(self.title, canvas)
            cv2.waitKey(1)
            self._last_update_at = now
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if not self._first_frame_logged:
                print(f"[debug] First overlay frame rendered in {elapsed_ms:.1f} ms.")
                self._first_frame_logged = True
            return True, elapsed_ms
        except Exception as exc:
            self._available = False
            print(f"[debug] Overlay disabled during update: {exc}")
            return False, 0.0

    def stop(self) -> None:
        if not self.active:
            return
        try:
            cv2.destroyWindow(self.title)
        except Exception:
            pass
        self._available = False

    def _render_preview(self, snapshot: DetectionSnapshot, state: RealtimeDebugState) -> np.ndarray:
        canvas = self._build_base_frame(snapshot)
        self._draw_custom_annotations(canvas, snapshot)
        self._draw_status_text(canvas, build_debug_lines(state))
        return cv2.resize(canvas, (self.cfg.window_width, self.cfg.window_height), interpolation=cv2.INTER_AREA)

    def _build_base_frame(self, snapshot: DetectionSnapshot) -> np.ndarray:
        if snapshot.raw_result is not None:
            try:
                plotted = snapshot.raw_result.plot()
                if plotted is not None:
                    return plotted.copy()
            except Exception:
                pass
        if snapshot.frame_image is not None:
            return snapshot.frame_image.copy()
        return np.full((self.cfg.window_height, self.cfg.window_width, 3), 18, dtype=np.uint8)

    def _draw_custom_annotations(self, canvas: np.ndarray, snapshot: DetectionSnapshot) -> None:
        height, width = canvas.shape[:2]
        center = (width // 2, height // 2)
        cv2.drawMarker(
            canvas,
            center,
            (255, 255, 255),
            markerType=cv2.MARKER_CROSS,
            markerSize=16,
            thickness=1,
        )
        for index, det in enumerate(snapshot.detections):
            is_primary = index == snapshot.primary_index
            color = (64, 220, 64) if is_primary else (0, 165, 255)
            p1 = (int(det.x1), int(det.y1))
            p2 = (int(det.x2), int(det.y2))
            aim = (int(det.aim_x), int(det.aim_y))
            cv2.rectangle(canvas, p1, p2, color, 2 if is_primary else 1)
            cv2.circle(canvas, aim, 4, color, -1)
            if is_primary:
                cv2.line(canvas, center, aim, color, 2)

    def _draw_status_text(self, canvas: np.ndarray, lines: Iterable[str]) -> None:
        overlay = canvas.copy()
        panel_height = min(canvas.shape[0] - 8, 24 + (24 * len(list(lines))))
        cv2.rectangle(overlay, (8, 8), (min(canvas.shape[1] - 8, 520), panel_height), (12, 12, 12), -1)
        cv2.addWeighted(overlay, 0.45, canvas, 0.55, 0, canvas)
        y = 28
        for index, line in enumerate(lines):
            color = (255, 255, 255) if index == 0 else (220, 240, 220)
            scale = 0.60 if index == 0 else 0.48
            thickness = 2 if index == 0 else 1
            cv2.putText(
                canvas,
                line,
                (18, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                scale,
                color,
                thickness,
                cv2.LINE_AA,
            )
            y += 24

    def _compute_window_origin(self) -> tuple[int, int]:
        margin = max(0, int(self.cfg.top_right_margin))
        try:
            width = ctypes.windll.user32.GetSystemMetrics(0)
        except Exception:
            width = self.cfg.window_width + margin
        x = max(0, int(width - self.cfg.window_width - margin))
        y = margin
        return x, y

    def _maybe_save_debug_images(self, snapshot: DetectionSnapshot, canvas: np.ndarray, now: float) -> None:
        if not self.cfg.save_frames:
            return
        interval = max(0.0, float(self.cfg.save_interval_sec))
        if self._last_saved_at and (now - self._last_saved_at) < interval:
            return
        capture_path = self._save_dir / "latest_capture.png"
        preview_path = self._save_dir / "latest_preview.png"
        if snapshot.frame_image is not None:
            cv2.imwrite(str(capture_path), snapshot.frame_image)
        cv2.imwrite(str(preview_path), canvas)
        self._last_saved_at = now
        if self._last_saved_at == now and interval == 0.0:
            return
        print(f"[debug] Saved capture to {capture_path} and preview to {preview_path}")

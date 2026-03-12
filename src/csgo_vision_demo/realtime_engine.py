from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time

import numpy as np

from .capture import CaptureConfig, ScreenCapture
from .config import RealtimeConfig
from .detection_normalizer import DetectionRecord, extract_detection_records, list_model_classes
from .model_runner import ModelRunner


@dataclass
class CaptureFrame:
    frame_id: int
    captured_at: float
    image: np.ndarray


@dataclass
class DetectionSnapshot:
    status: str
    frame_id: int
    captured_at: float
    frame_image: np.ndarray | None = None
    raw_result: object | None = None
    detections: list[DetectionRecord] = field(default_factory=list)
    primary_index: int | None = None
    inference_ms: float = 0.0
    reason: str = ""
    error: str | None = None
    loop_ms: float = 0.0

    @property
    def primary_target(self) -> DetectionRecord | None:
        if self.primary_index is None or self.primary_index >= len(self.detections):
            return None
        return self.detections[self.primary_index]


class _LatestFrameBuffer:
    def __init__(self) -> None:
        self._frame: CaptureFrame | None = None
        self._lock = threading.Lock()

    def put(self, frame: CaptureFrame) -> None:
        with self._lock:
            self._frame = frame

    def get(self) -> CaptureFrame | None:
        with self._lock:
            return self._frame


class _CaptureWorker(threading.Thread):
    def __init__(self, capture_config: CaptureConfig, buf: _LatestFrameBuffer, sleep_ms: float) -> None:
        super().__init__(daemon=True, name="capture-worker")
        self._capture_config = capture_config
        self._buf = buf
        self._sleep_sec = max(0.0, sleep_ms / 1000.0)
        self._stop_event = threading.Event()
        self.last_error: str | None = None
        self.frame_id = 0
        self.opened = False
        self.width = 0
        self.height = 0

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        capture = ScreenCapture(self._capture_config)
        try:
            capture.open()
            self.opened = True
            self.width = capture.width
            self.height = capture.height
            print(f"[capture] Opened region {capture.width}x{capture.height}.")
            while not self._stop_event.is_set():
                try:
                    image = capture.grab()
                    self.frame_id += 1
                    self._buf.put(CaptureFrame(self.frame_id, time.perf_counter(), image))
                    self.last_error = None
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    if self.frame_id == 0:
                        print(f"[capture] First frame failed: {self.last_error}")
                if self._sleep_sec:
                    time.sleep(self._sleep_sec)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            print(f"[capture] Worker failed to open capture: {self.last_error}")
        finally:
            capture.close()


class DetectionEngine:
    def __init__(self, cfg: RealtimeConfig) -> None:
        self.cfg = cfg
        self.capture_config = CaptureConfig(
            method=cfg.capture.method,
            region=cfg.capture.region,
            center_crop_size=cfg.capture.center_crop_size,
            monitor_index=cfg.capture.monitor_index,
        )
        self.capture = ScreenCapture(self.capture_config)
        self.model_runner = ModelRunner(
            model_path=cfg.model.path,
            confidence=cfg.model.confidence,
            imgsz=cfg.model.imgsz,
            device=cfg.model.device,
        )
        self._buffer = _LatestFrameBuffer()
        self._capture_worker: _CaptureWorker | None = None
        self._class_names: dict[int, str] = {}
        self._last_consumed_frame_id = -1
        self.status = "starting"
        self.last_snapshot = DetectionSnapshot(status="starting", frame_id=0, captured_at=0.0, reason="starting")
        self.capture_width = 0
        self.capture_height = 0

    def start(self) -> None:
        self._capture_worker = _CaptureWorker(self.capture_config, self._buffer, self.cfg.runtime.capture_sleep_ms)
        self._capture_worker.start()
        self._set_status("warming_up")
        warmup_frame = self._wait_for_frame(timeout_sec=5.0)
        if warmup_frame is None:
            self._set_status("failed")
            last_error = self._capture_worker.last_error if self._capture_worker is not None else None
            suffix = f" Last capture error: {last_error}" if last_error else ""
            raise RuntimeError(f"No frame captured during engine startup.{suffix}")
        self.capture_width = self._capture_worker.width
        self.capture_height = self._capture_worker.height
        for _ in range(max(1, int(self.cfg.runtime.warmup_frames))):
            self.model_runner.warmup(warmup_frame.image)
        self._class_names = list_model_classes(self.model_runner.model)
        self._set_status("running")
        print(f"[engine] Running with model {self.cfg.model.path}")

    def stop(self) -> None:
        self._set_status("stopping")
        if self._capture_worker is not None:
            self._capture_worker.stop()
            self._capture_worker.join(timeout=2.0)
            self._capture_worker = None
        self._set_status("stopped")

    def poll(self) -> DetectionSnapshot:
        started = time.perf_counter()
        frame = self._buffer.get()
        if frame is None:
            snapshot = DetectionSnapshot(
                status=self.status,
                frame_id=0,
                captured_at=0.0,
                reason="waiting for capture frame",
                error=self._capture_worker.last_error if self._capture_worker is not None else None,
                loop_ms=(time.perf_counter() - started) * 1000.0,
            )
            self.last_snapshot = snapshot
            return snapshot

        stale_ms = (time.perf_counter() - frame.captured_at) * 1000.0
        if stale_ms > float(self.cfg.runtime.max_stale_frame_ms):
            self._set_status("degraded")
            snapshot = DetectionSnapshot(
                status=self.status,
                frame_id=frame.frame_id,
                captured_at=frame.captured_at,
                frame_image=frame.image,
                reason=f"stale frame ({stale_ms:.1f} ms)",
                loop_ms=(time.perf_counter() - started) * 1000.0,
            )
            self.last_snapshot = snapshot
            return snapshot

        if frame.frame_id == self._last_consumed_frame_id:
            self.last_snapshot.loop_ms = (time.perf_counter() - started) * 1000.0
            return self.last_snapshot

        self._last_consumed_frame_id = frame.frame_id
        run = self.model_runner.predict(frame.image)
        if run.error is not None or run.result is None:
            self._set_status("degraded")
            snapshot = DetectionSnapshot(
                status=self.status,
                frame_id=frame.frame_id,
                captured_at=frame.captured_at,
                frame_image=frame.image,
                inference_ms=run.inference_ms,
                reason="inference failed",
                error=run.error,
                loop_ms=(time.perf_counter() - started) * 1000.0,
            )
            self.last_snapshot = snapshot
            return snapshot

        detections, primary_index = extract_detection_records(
            run.result,
            frame.image.shape[:2],
            self._class_names,
            target_class_names=set(self.cfg.model.target_class_names),
            target_class_ids=set(self.cfg.model.target_class_ids),
            aim_mode=self.cfg.aim.mode,
            target_strategy=self.cfg.aim.target_strategy,
            min_keypoint_confidence=self.cfg.aim.min_keypoint_confidence,
            head_fraction=self.cfg.aim.head_fraction,
        )
        self._set_status("running")
        snapshot = DetectionSnapshot(
            status=self.status,
            frame_id=frame.frame_id,
            captured_at=frame.captured_at,
            frame_image=frame.image,
            raw_result=run.result,
            detections=detections,
            primary_index=primary_index,
            inference_ms=run.inference_ms,
            reason="ok" if primary_index is not None else "no target",
            loop_ms=(time.perf_counter() - started) * 1000.0,
        )
        self.last_snapshot = snapshot
        return snapshot

    def _wait_for_frame(self, timeout_sec: float) -> CaptureFrame | None:
        deadline = time.perf_counter() + timeout_sec
        while time.perf_counter() < deadline:
            frame = self._buffer.get()
            if frame is not None:
                return frame
            time.sleep(0.01)
        return None

    def _set_status(self, status: str) -> None:
        if self.status != status:
            print(f"[engine] Status {self.status} -> {status}")
            self.status = status

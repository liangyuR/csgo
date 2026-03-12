from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2

from .detection_normalizer import DetectionRecord, extract_detection_records, list_model_classes

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".wmv"}


@dataclass
class ProcessSummary:
    input_path: str
    output_dir: str
    media_type: str
    files_processed: int
    frames_processed: int
    detections_written: int


class OfflineAimAnalyzer:
    def __init__(
        self,
        model_path: str | Path,
        confidence: float = 0.35,
        imgsz: int = 960,
        device: str | None = None,
        target_class_names: list[str] | None = None,
        target_class_ids: list[int] | None = None,
        aim_mode: str = "center",
        head_fraction: float = 0.18,
    ) -> None:
        self.model_path = Path(model_path)
        self.confidence = confidence
        self.imgsz = imgsz
        self.device = device
        self.target_class_names = set(target_class_names or [])
        self.target_class_ids = set(target_class_ids or [])
        self.aim_mode = aim_mode
        self.head_fraction = head_fraction
        self._model = None

    @property
    def model(self):
        if self._model is None:
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise RuntimeError(
                    "ultralytics is not installed. Run: pip install -r requirements.txt"
                ) from exc
            self._model = YOLO(str(self.model_path))
        return self._model

    def list_classes(self) -> dict[int, str]:
        return list_model_classes(self.model)

    def analyze_frame(self, frame) -> tuple[list[DetectionRecord], int | None]:
        result = self.model.predict(
            source=frame,
            conf=self.confidence,
            imgsz=self.imgsz,
            device=self.device,
            verbose=False,
        )[0]
        return extract_detection_records(
            result,
            frame.shape[:2],
            self.list_classes(),
            target_class_names=self.target_class_names,
            target_class_ids=self.target_class_ids,
            aim_mode=self.aim_mode,
            target_strategy="nearest_head_to_center",
            min_keypoint_confidence=0.35,
            head_fraction=self.head_fraction,
        )

    def annotate_frame(self, frame, detections: list[DetectionRecord], primary_index: int | None):
        canvas = frame.copy()
        height, width = canvas.shape[:2]
        center = (width // 2, height // 2)

        cv2.drawMarker(
            canvas,
            center,
            (255, 255, 255),
            markerType=cv2.MARKER_CROSS,
            markerSize=20,
            thickness=1,
        )

        for idx, det in enumerate(detections):
            is_primary = idx == primary_index
            color = (64, 220, 64) if is_primary else (0, 165, 255)
            p1 = (int(det.x1), int(det.y1))
            p2 = (int(det.x2), int(det.y2))
            aim = (int(det.aim_x), int(det.aim_y))
            label = f"{det.class_name} {det.confidence:.2f}"

            cv2.rectangle(canvas, p1, p2, color, 2)
            cv2.circle(canvas, aim, 5, color, -1)
            cv2.putText(
                canvas,
                label,
                (p1[0], max(20, p1[1] - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
                cv2.LINE_AA,
            )
            cv2.putText(
                canvas,
                f"{det.aim_source} dx={det.offset_x:.0f}, dy={det.offset_y:.0f}",
                (p1[0], min(height - 12, p2[1] + 18)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                color,
                1,
                cv2.LINE_AA,
            )
            if is_primary:
                cv2.line(canvas, center, aim, (64, 220, 64), 2)

        return canvas


def ensure_output_dir(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    annotated_dir = output_dir / "annotated"
    annotated_dir.mkdir(parents=True, exist_ok=True)
    return annotated_dir


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def collect_inputs(source: Path) -> tuple[str, list[Path]]:
    if source.is_dir():
        files = sorted(path for path in source.iterdir() if is_image(path))
        return "image_dir", files
    if is_image(source):
        return "image", [source]
    if is_video(source):
        return "video", [source]
    raise ValueError(f"Unsupported input source: {source}")


def write_csv(rows: list[DetectionRecord], output_path: Path) -> None:
    fieldnames = list(DetectionRecord.__dataclass_fields__.keys())
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_summary(summary: ProcessSummary, output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(summary), handle, indent=2, ensure_ascii=False)


def process_images(analyzer: OfflineAimAnalyzer, images: list[Path], output_dir: Path) -> ProcessSummary:
    annotated_dir = ensure_output_dir(output_dir)
    rows: list[DetectionRecord] = []
    frames_processed = 0

    for image_path in images:
        frame = cv2.imread(str(image_path))
        if frame is None:
            continue
        detections, primary_index = analyzer.analyze_frame(frame)
        annotated = analyzer.annotate_frame(frame, detections, primary_index)

        for det in detections:
            det.source_file = image_path.name
            det.frame_index = 0
        rows.extend(detections)

        output_path = annotated_dir / f"{image_path.stem}_annotated{image_path.suffix}"
        cv2.imwrite(str(output_path), annotated)
        frames_processed += 1

    write_csv(rows, output_dir / "detections.csv")
    summary = ProcessSummary(
        input_path=str(images[0].parent if len(images) > 1 else images[0]),
        output_dir=str(output_dir),
        media_type="image" if len(images) == 1 else "image_dir",
        files_processed=len(images),
        frames_processed=frames_processed,
        detections_written=len(rows),
    )
    write_summary(summary, output_dir / "summary.json")
    return summary


def process_video(analyzer: OfflineAimAnalyzer, video_path: Path, output_dir: Path) -> ProcessSummary:
    annotated_dir = ensure_output_dir(output_dir)
    rows: list[DetectionRecord] = []

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    output_video = annotated_dir / f"{video_path.stem}_annotated.mp4"
    writer = cv2.VideoWriter(
        str(output_video),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    frame_index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        detections, primary_index = analyzer.analyze_frame(frame)
        annotated = analyzer.annotate_frame(frame, detections, primary_index)
        writer.write(annotated)

        for det in detections:
            det.source_file = video_path.name
            det.frame_index = frame_index
        rows.extend(detections)
        frame_index += 1

    capture.release()
    writer.release()

    write_csv(rows, output_dir / "detections.csv")
    summary = ProcessSummary(
        input_path=str(video_path),
        output_dir=str(output_dir),
        media_type="video",
        files_processed=1,
        frames_processed=frame_index if frame_index else frame_count,
        detections_written=len(rows),
    )
    write_summary(summary, output_dir / "summary.json")
    return summary


def run_pipeline(
    source: str | Path,
    output_dir: str | Path,
    analyzer: OfflineAimAnalyzer,
) -> ProcessSummary:
    source_path = Path(source)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    media_type, inputs = collect_inputs(source_path)
    if not inputs:
        raise RuntimeError(f"No supported files found in: {source_path}")

    if media_type == "video":
        return process_video(analyzer, inputs[0], output_path)
    return process_images(analyzer, inputs, output_path)

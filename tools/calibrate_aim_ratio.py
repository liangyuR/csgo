"""Calibrate aim_pixel_ratio_x/y from real screen motion.

The script sends known mouse deltas, measures the visual screen displacement
between before/after frames, and writes the resulting pixel-per-mouse-count
ratios into config.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from statistics import median
from typing import Callable, Iterable, Sequence

import numpy as np


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


RatioWriter = Callable[[int, int, str], None]

MIN_RATIO = 0.1
MAX_RATIO = 10.0
DEFAULT_CONFIG_PATH = os.path.join(ROOT, "config.json")


@dataclass(frozen=True)
class AxisCalibration:
    axis: str
    ratio: float
    samples: tuple[float, ...]
    median_shift_px: float


def clamp_ratio(value: float) -> float:
    return max(MIN_RATIO, min(MAX_RATIO, float(value)))


def center_crop(image: np.ndarray, fraction: float) -> np.ndarray:
    if image.ndim < 2:
        raise ValueError("image must have at least two dimensions")

    safe_fraction = max(0.1, min(1.0, float(fraction)))
    height, width = image.shape[:2]
    crop_width = max(8, int(width * safe_fraction))
    crop_height = max(8, int(height * safe_fraction))
    left = max(0, (width - crop_width) // 2)
    top = max(0, (height - crop_height) // 2)
    return image[top : top + crop_height, left : left + crop_width]


def to_gray_float32(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        gray = image
    elif image.ndim == 3 and image.shape[2] >= 3:
        rgb = image[:, :, :3].astype(np.float32)
        gray = (0.299 * rgb[:, :, 0]) + (0.587 * rgb[:, :, 1]) + (0.114 * rgb[:, :, 2])
    else:
        raise ValueError(f"unsupported image shape: {image.shape!r}")
    return np.ascontiguousarray(gray.astype(np.float32))


def estimate_shift_px(before: np.ndarray, after: np.ndarray, roi_fraction: float = 0.65) -> tuple[float, float]:
    """Return the visual shift in pixels from before to after.

    Uses OpenCV phase correlation. The return value is signed, but calibration
    consumes absolute shifts because game camera direction can differ by title
    and input backend.
    """

    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("OpenCV (cv2) is required for phase-correlation calibration") from exc

    before_gray = to_gray_float32(center_crop(np.asarray(before), roi_fraction))
    after_gray = to_gray_float32(center_crop(np.asarray(after), roi_fraction))
    if before_gray.shape != after_gray.shape:
        raise ValueError(f"frame shapes differ after crop: {before_gray.shape!r} != {after_gray.shape!r}")

    window = cv2.createHanningWindow((before_gray.shape[1], before_gray.shape[0]), cv2.CV_32F)
    shift, _response = cv2.phaseCorrelate(before_gray, after_gray, window)
    return float(shift[0]), float(shift[1])


def ratio_from_shifts(shifts_px: Iterable[float], mouse_counts: int) -> tuple[float, tuple[float, ...], float]:
    magnitudes = tuple(abs(float(shift)) for shift in shifts_px if np.isfinite(float(shift)))
    if not magnitudes:
        raise RuntimeError("no finite displacement samples were measured")

    denominator = abs(int(mouse_counts))
    if denominator <= 0:
        raise ValueError("mouse_counts must be non-zero")

    median_shift = float(median(magnitudes))
    if median_shift <= 0.0:
        raise RuntimeError("measured displacement is zero; make sure the game view is active and textured")
    return clamp_ratio(median_shift / denominator), magnitudes, median_shift


def update_config_file(config_path: str, ratio_x: float, ratio_y: float, dry_run: bool = False) -> dict:
    data: dict = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

    data["aim_pixel_ratio_x"] = clamp_ratio(ratio_x)
    data["aim_pixel_ratio_y"] = clamp_ratio(ratio_y)

    if not dry_run:
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return data


def _capture_frame(camera) -> np.ndarray:
    frame = camera.grab()
    if frame is None and hasattr(camera, "get_latest_frame"):
        frame = camera.get_latest_frame()
    if frame is None:
        raise RuntimeError("dxcam returned no frame")
    return np.asarray(frame)


def calibrate_axis(
    axis: str,
    camera,
    send_move: RatioWriter,
    mouse_counts: int,
    samples: int,
    mouse_method: str,
    settle_s: float,
    roi_fraction: float,
) -> AxisCalibration:
    axis_name = axis.lower()
    if axis_name not in {"x", "y"}:
        raise ValueError("axis must be 'x' or 'y'")

    shifts: list[float] = []
    for _ in range(max(1, int(samples))):
        before = _capture_frame(camera)
        if axis_name == "x":
            send_move(int(mouse_counts), 0, mouse_method)
        else:
            send_move(0, int(mouse_counts), mouse_method)
        time.sleep(max(0.0, float(settle_s)))
        after = _capture_frame(camera)
        shift_x, shift_y = estimate_shift_px(before, after, roi_fraction)
        shifts.append(shift_x if axis_name == "x" else shift_y)

        # Move back near the original view to keep consecutive samples comparable.
        if axis_name == "x":
            send_move(-int(mouse_counts), 0, mouse_method)
        else:
            send_move(0, -int(mouse_counts), mouse_method)
        time.sleep(max(0.0, float(settle_s)))

    ratio, magnitudes, median_shift = ratio_from_shifts(shifts, mouse_counts)
    return AxisCalibration(axis_name, ratio, magnitudes, median_shift)


def create_dxcam_camera():
    try:
        import dxcam  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("dxcam is required for aim-ratio calibration") from exc

    camera = dxcam.create(output_color="RGB")
    if camera is None:
        raise RuntimeError("dxcam.create returned no camera")
    return camera


def run_calibration(args: argparse.Namespace) -> int:
    from win_utils import send_mouse_move

    camera = create_dxcam_camera()
    time.sleep(max(0.0, float(args.warmup_s)))

    print("Keep CS2 focused on a textured scene. Calibration starts now.")
    x_result = calibrate_axis(
        "x",
        camera,
        send_mouse_move,
        args.mouse_counts,
        args.samples,
        args.mouse_method,
        args.settle_s,
        args.roi_fraction,
    )
    y_result = calibrate_axis(
        "y",
        camera,
        send_mouse_move,
        args.mouse_counts,
        args.samples,
        args.mouse_method,
        args.settle_s,
        args.roi_fraction,
    )

    update_config_file(args.config, x_result.ratio, y_result.ratio, dry_run=args.dry_run)

    print(f"aim_pixel_ratio_x={x_result.ratio:.4f} (median shift {x_result.median_shift_px:.2f}px)")
    print(f"aim_pixel_ratio_y={y_result.ratio:.4f} (median shift {y_result.median_shift_px:.2f}px)")
    if args.dry_run:
        print("Dry run: config.json was not modified.")
    else:
        print(f"Updated {args.config}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calibrate aim_pixel_ratio_x/y and write config.json")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to config.json")
    parser.add_argument("--mouse-counts", type=int, default=120, help="Mouse counts to send per sample")
    parser.add_argument("--samples", type=int, default=5, help="Samples per axis")
    parser.add_argument("--settle-s", type=float, default=0.12, help="Delay after each mouse move")
    parser.add_argument("--warmup-s", type=float, default=1.0, help="Delay before first capture")
    parser.add_argument("--roi-fraction", type=float, default=0.65, help="Center ROI fraction used for correlation")
    parser.add_argument(
        "--mouse-method",
        default="mouse_event",
        choices=("mouse_event", "sendinput", "ddxoft", "arduino", "xbox"),
        help="Mouse movement backend",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print ratios without writing config.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mouse_counts == 0:
        raise SystemExit("--mouse-counts must be non-zero")
    return run_calibration(args)


if __name__ == "__main__":
    raise SystemExit(main())

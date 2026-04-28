"""Calibrate aim_pixel_ratio_x/y from real screen motion.

The script sends known mouse deltas, measures the visual screen displacement
between before/after frames, and writes the resulting pixel-per-mouse-count
ratios into config.json.
"""

from __future__ import annotations

import argparse
import ctypes
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
MIN_MOUSE_COUNTS = 8
MAX_AUTO_TUNE_ATTEMPTS = 3
LOW_SHIFT_MIN_PX = 5.0
LOW_SHIFT_ROI_FRACTION = 0.005
HIGH_SHIFT_ROI_FRACTION = 0.4
HIGH_VARIANCE_RATIO = 0.15
DEFAULT_CONFIG_PATH = os.path.join(ROOT, "config.json")
VALID_MOUSE_METHODS = {"mouse_event", "sendinput", "ddxoft", "arduino", "xbox", "auto"}
CALIBRATABLE_MOUSE_METHODS = {"mouse_event", "sendinput", "ddxoft", "arduino"}


@dataclass(frozen=True)
class AxisCalibration:
    axis: str
    ratio: float
    samples: tuple[float, ...]
    median_shift_px: float
    mad_px: float
    mouse_counts: int


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


def axis_crop(image: np.ndarray, fraction: float, axis: str = "x") -> np.ndarray:
    if image.ndim < 2:
        raise ValueError("image must have at least two dimensions")

    axis_name = axis.lower()
    if axis_name not in {"x", "y"}:
        raise ValueError("axis must be 'x' or 'y'")
    if axis_name == "x":
        return center_crop(image, fraction)

    safe_fraction = max(0.1, min(1.0, float(fraction)))
    height, width = image.shape[:2]
    crop_width = max(8, int(width * safe_fraction))
    crop_height = max(8, int(height * safe_fraction))
    left = max(0, (width - crop_width) // 2)
    center_y = int(height * 0.4)
    top = max(0, min(height - crop_height, center_y - (crop_height // 2)))
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


def _write_debug_image(cv2, path: str, image: np.ndarray) -> None:
    array = np.asarray(image)
    if array.dtype != np.uint8:
        finite = array[np.isfinite(array)]
        if finite.size:
            minimum = float(finite.min())
            maximum = float(finite.max())
            if maximum > minimum:
                array = ((array.astype(np.float32) - minimum) * (255.0 / (maximum - minimum))).clip(0, 255)
            else:
                array = np.zeros_like(array, dtype=np.float32)
        array = array.astype(np.uint8)
    if array.ndim == 3 and array.shape[2] >= 3:
        array = array[:, :, :3][:, :, ::-1]
    cv2.imwrite(path, array)


def _save_debug_images(
    cv2,
    debug_save_dir: str | None,
    debug_name: str | None,
    before: np.ndarray,
    after: np.ndarray,
    before_roi: np.ndarray,
    after_roi: np.ndarray,
) -> None:
    if not debug_save_dir:
        return

    os.makedirs(debug_save_dir, exist_ok=True)
    safe_name = debug_name or f"sample_{int(time.time() * 1000)}"
    images = (
        ("before", before),
        ("after", after),
        ("before_roi", before_roi),
        ("after_roi", after_roi),
    )
    for suffix, image in images:
        _write_debug_image(cv2, os.path.join(debug_save_dir, f"{safe_name}_{suffix}.png"), image)


def estimate_shift_px(
    before: np.ndarray,
    after: np.ndarray,
    roi_fraction: float = 0.65,
    axis: str = "x",
    debug_save_dir: str | None = None,
    debug_name: str | None = None,
) -> tuple[float, float]:
    """Return the visual shift in pixels from before to after.

    Uses OpenCV phase correlation. The return value is signed, but calibration
    consumes absolute shifts because game camera direction can differ by title
    and input backend.
    """

    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("OpenCV (cv2) is required for phase-correlation calibration") from exc

    before_array = np.asarray(before)
    after_array = np.asarray(after)
    before_roi = axis_crop(before_array, roi_fraction, axis)
    after_roi = axis_crop(after_array, roi_fraction, axis)
    before_gray = to_gray_float32(before_roi)
    after_gray = to_gray_float32(after_roi)
    if before_gray.shape != after_gray.shape:
        raise ValueError(f"frame shapes differ after crop: {before_gray.shape!r} != {after_gray.shape!r}")

    _save_debug_images(cv2, debug_save_dir, debug_name, before_array, after_array, before_roi, after_roi)

    window = cv2.createHanningWindow((before_gray.shape[1], before_gray.shape[0]), cv2.CV_32F)
    shift, _response = cv2.phaseCorrelate(before_gray, after_gray, window)
    return float(shift[0]), float(shift[1])


def ratio_from_shifts(shifts_px: Iterable[float], mouse_counts: int) -> tuple[float, tuple[float, ...], float, float]:
    magnitudes = tuple(abs(float(shift)) for shift in shifts_px if np.isfinite(float(shift)))
    if not magnitudes:
        raise RuntimeError("no finite displacement samples were measured")

    denominator = abs(int(mouse_counts))
    if denominator <= 0:
        raise ValueError("mouse_counts must be non-zero")

    median_shift = float(median(magnitudes))
    if median_shift <= 0.0:
        raise RuntimeError("measured displacement is zero; make sure the game view is active and textured")
    mad_px = float(median(abs(value - median_shift) for value in magnitudes))
    return clamp_ratio(median_shift / denominator), magnitudes, median_shift, mad_px


def read_config_data(config_path: str) -> dict:
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_mouse_method(cli_mouse_method: str | None, config_path: str) -> str:
    if cli_mouse_method:
        method = str(cli_mouse_method).lower()
    else:
        method = str(read_config_data(config_path).get("mouse_move_method", "mouse_event") or "mouse_event").lower()

    if method == "hardware":
        method = "mouse_event"
    if method not in VALID_MOUSE_METHODS:
        raise RuntimeError(f"unsupported mouse backend for calibration: {method}")
    if method not in CALIBRATABLE_MOUSE_METHODS:
        raise RuntimeError(
            f"mouse backend {method!r} cannot be calibrated with pixel displacement; choose mouse_event, sendinput, ddxoft, or arduino"
        )
    return method


def update_config_file(config_path: str, ratio_x: float, ratio_y: float, dry_run: bool = False) -> dict:
    data = read_config_data(config_path)

    data["aim_pixel_ratio_x"] = clamp_ratio(ratio_x)
    data["aim_pixel_ratio_y"] = clamp_ratio(ratio_y)

    if not dry_run:
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return data


def _grab_fresh_frame(camera, timeout_s: float = 0.25) -> np.ndarray:
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while True:
        frame = camera.grab()
        if frame is not None:
            return np.asarray(frame)
        if time.monotonic() >= deadline:
            raise RuntimeError("dxcam timed out waiting for fresh frame")
        time.sleep(0.005)


def _capture_frame(camera, timeout_s: float = 0.25) -> np.ndarray:
    frame = _grab_fresh_frame(camera, timeout_s=timeout_s)
    return np.asarray(frame)


def _axis_component(shift: tuple[float, float], axis_name: str) -> float:
    return shift[0] if axis_name == "x" else shift[1]


def _roi_axis_dimension(frame: np.ndarray, axis_name: str, roi_fraction: float) -> int:
    roi = axis_crop(np.asarray(frame), roi_fraction, axis_name)
    return int(roi.shape[1] if axis_name == "x" else roi.shape[0])


def _sample_axis_pair(
    axis_name: str,
    camera,
    send_move: RatioWriter,
    mouse_counts: int,
    mouse_method: str,
    settle_s: float,
    roi_fraction: float,
    fresh_timeout_s: float,
    debug_save_dir: str | None,
    debug_name_prefix: str,
) -> tuple[list[float], int]:
    if axis_name == "x":
        forward = (int(mouse_counts), 0)
        reverse = (-int(mouse_counts), 0)
    else:
        forward = (0, int(mouse_counts))
        reverse = (0, -int(mouse_counts))

    before = _capture_frame(camera, timeout_s=fresh_timeout_s)
    roi_dim = _roi_axis_dimension(before, axis_name, roi_fraction)

    send_move(forward[0], forward[1], mouse_method)
    time.sleep(max(0.0, float(settle_s)))
    after_forward = _capture_frame(camera, timeout_s=fresh_timeout_s)
    shift_forward = estimate_shift_px(
        before,
        after_forward,
        roi_fraction,
        axis_name,
        debug_save_dir,
        f"{debug_name_prefix}_fwd",
    )

    send_move(reverse[0], reverse[1], mouse_method)
    time.sleep(max(0.0, float(settle_s)))
    after_reverse = _capture_frame(camera, timeout_s=fresh_timeout_s)
    shift_reverse = estimate_shift_px(
        after_forward,
        after_reverse,
        roi_fraction,
        axis_name,
        debug_save_dir,
        f"{debug_name_prefix}_rev",
    )

    return [_axis_component(shift_forward, axis_name), _axis_component(shift_reverse, axis_name)], roi_dim


def _tune_counts(current_abs_counts: int, median_shift_px: float, roi_axis_dim: int) -> int:
    low_threshold = max(LOW_SHIFT_MIN_PX, roi_axis_dim * LOW_SHIFT_ROI_FRACTION)
    high_threshold = roi_axis_dim * HIGH_SHIFT_ROI_FRACTION
    if median_shift_px < low_threshold:
        return current_abs_counts * 2
    if median_shift_px > high_threshold:
        return max(MIN_MOUSE_COUNTS, current_abs_counts // 2)
    return current_abs_counts


def calibrate_axis(
    axis: str,
    camera,
    send_move: RatioWriter,
    mouse_counts: int,
    samples: int,
    mouse_method: str,
    settle_s: float,
    roi_fraction: float,
    fresh_timeout_s: float = 0.25,
    auto_tune: bool = True,
    debug_save_dir: str | None = None,
) -> AxisCalibration:
    axis_name = axis.lower()
    if axis_name not in {"x", "y"}:
        raise ValueError("axis must be 'x' or 'y'")

    requested_counts = int(mouse_counts)
    if requested_counts == 0:
        raise ValueError("mouse_counts must be non-zero")
    count_sign = -1 if requested_counts < 0 else 1
    current_abs_counts = max(MIN_MOUSE_COUNTS, abs(requested_counts))

    shifts: list[float] = []
    sample_pairs = max(1, int(samples))
    measured_pairs = 0
    tune_attempts = 0
    debug_index = 0

    while measured_pairs < sample_pairs:
        signed_counts = current_abs_counts * count_sign
        pair_shifts, roi_axis_dim = _sample_axis_pair(
            axis_name,
            camera,
            send_move,
            signed_counts,
            mouse_method,
            settle_s,
            roi_fraction,
            fresh_timeout_s,
            debug_save_dir,
            f"{axis_name}_{debug_index:03d}",
        )
        debug_index += 1

        if auto_tune and measured_pairs == 0:
            pair_median = float(median(abs(value) for value in pair_shifts))
            tuned_abs_counts = _tune_counts(current_abs_counts, pair_median, roi_axis_dim)
            if tuned_abs_counts != current_abs_counts and tune_attempts < MAX_AUTO_TUNE_ATTEMPTS:
                direction = "increasing" if tuned_abs_counts > current_abs_counts else "decreasing"
                print(
                    f"{axis_name.upper()} axis: measured {pair_median:.2f}px with counts={signed_counts}; "
                    f"{direction} mouse_counts to {tuned_abs_counts * count_sign}"
                )
                current_abs_counts = tuned_abs_counts
                tune_attempts += 1
                continue

        shifts.extend(pair_shifts)
        measured_pairs += 1

    final_counts = current_abs_counts * count_sign
    ratio, magnitudes, median_shift, mad_px = ratio_from_shifts(shifts, final_counts)
    return AxisCalibration(axis_name, ratio, magnitudes, median_shift, mad_px, final_counts)


def create_dxcam_camera():
    try:
        import dxcam  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("dxcam is required for aim-ratio calibration") from exc

    camera = dxcam.create(output_color="RGB")
    if camera is None:
        raise RuntimeError("dxcam.create returned no camera")
    if hasattr(camera, "start"):
        try:
            camera.start(target_fps=60)
        except TypeError:
            camera.start()
    return camera


def get_foreground_window_title() -> str:
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value
    except Exception:
        return ""


def run_countdown(countdown: int) -> None:
    seconds = max(0, int(countdown))
    if seconds <= 0:
        return
    title = get_foreground_window_title()
    if title:
        print(f"Active window: {title}")
        normalized = title.lower()
        if "cs2" not in normalized and "counter-strike" not in normalized:
            print("WARNING: active window does not look like CS2; focus the game before calibration starts.")
    for value in range(seconds, 0, -1):
        print(value)
        time.sleep(1.0)


def _print_axis_result(result: AxisCalibration) -> None:
    print(
        f"aim_pixel_ratio_{result.axis}={result.ratio:.4f} "
        f"(median {result.median_shift_px:.2f}px, MAD {result.mad_px:.2f}px, "
        f"samples={len(result.samples)}, counts={result.mouse_counts})"
    )
    if result.median_shift_px > 0.0 and (result.mad_px / result.median_shift_px) > HIGH_VARIANCE_RATIO:
        print("WARNING: high variance, consider re-running on a more textured scene")


def run_calibration(args: argparse.Namespace) -> int:
    mouse_method = resolve_mouse_method(args.mouse_method, args.config)
    print(f"Calibrating with backend={mouse_method}")
    from win_utils import send_mouse_move

    camera = None
    try:
        camera = create_dxcam_camera()
        time.sleep(max(0.0, float(args.warmup_s)))
        run_countdown(args.countdown)

        print("Keep CS2 focused on a textured scene. Calibration starts now.")
        x_result = calibrate_axis(
            "x",
            camera,
            send_mouse_move,
            args.mouse_counts,
            args.samples,
            mouse_method,
            args.settle_s,
            args.roi_fraction,
            args.fresh_timeout_s,
            auto_tune=not args.no_auto_tune,
            debug_save_dir=args.debug_save,
        )
        y_result = calibrate_axis(
            "y",
            camera,
            send_mouse_move,
            args.mouse_counts,
            args.samples,
            mouse_method,
            args.settle_s,
            args.roi_fraction,
            args.fresh_timeout_s,
            auto_tune=not args.no_auto_tune,
            debug_save_dir=args.debug_save,
        )
    finally:
        if camera is not None and hasattr(camera, "stop"):
            camera.stop()

    update_config_file(args.config, x_result.ratio, y_result.ratio, dry_run=args.dry_run)

    _print_axis_result(x_result)
    _print_axis_result(y_result)
    if args.dry_run:
        print("Dry run: config.json was not modified.")
    else:
        print(
            f"Updated {args.config} "
            f"(mouse_method={mouse_method}, mouse_counts_x={x_result.mouse_counts}, mouse_counts_y={y_result.mouse_counts})"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calibrate aim_pixel_ratio_x/y and write config.json")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to config.json")
    parser.add_argument("--mouse-counts", type=int, default=120, help="Mouse counts to send per sample")
    parser.add_argument("--samples", type=int, default=5, help="Samples per axis")
    parser.add_argument("--settle-s", type=float, default=0.12, help="Delay after each mouse move")
    parser.add_argument("--warmup-s", type=float, default=1.0, help="Delay before first capture")
    parser.add_argument("--countdown", type=int, default=3, help="Seconds to count down before calibration starts")
    parser.add_argument("--roi-fraction", type=float, default=0.65, help="Center ROI fraction used for correlation")
    parser.add_argument("--fresh-timeout-s", type=float, default=0.25, help="Timeout while waiting for a fresh dxcam frame")
    parser.add_argument("--debug-save", default=None, help="Directory for debug before/after/ROI PNG captures")
    parser.add_argument("--no-auto-tune", action="store_true", help="Disable automatic mouse-count adjustment")
    parser.add_argument(
        "--mouse-method",
        default=None,
        choices=("mouse_event", "sendinput", "ddxoft", "arduino", "xbox", "auto"),
        help="Mouse backend (default: read from config.json)",
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

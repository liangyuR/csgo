import json
import os
import sys
import unittest
import uuid
from unittest import mock

import numpy as np


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TOOLS_DIR = os.path.join(ROOT, "tools")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)


import calibrate_aim_ratio as calibrator


class _FakeCamera:
    def __init__(self, frames):
        self._frames = list(frames)

    def grab(self):
        if not self._frames:
            raise AssertionError("fake camera ran out of frames")
        return self._frames.pop(0)


class CalibrateAimRatioTests(unittest.TestCase):
    def _temporary_config_path(self) -> str:
        path = os.path.join(ROOT, f".tmp_calibrate_config_{uuid.uuid4().hex}.json")
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_ratio_from_shifts_uses_abs_median_and_clamps(self) -> None:
        ratio, samples, median_shift = calibrator.ratio_from_shifts([-20.0, 30.0, 40.0], 100)

        self.assertEqual(samples, (20.0, 30.0, 40.0))
        self.assertAlmostEqual(median_shift, 30.0)
        self.assertAlmostEqual(ratio, 0.3)

        low_ratio, _, _ = calibrator.ratio_from_shifts([1.0], 100)
        high_ratio, _, _ = calibrator.ratio_from_shifts([5000.0], 100)

        self.assertAlmostEqual(low_ratio, 0.1)
        self.assertAlmostEqual(high_ratio, 10.0)

    def test_ratio_from_shifts_rejects_zero_or_invalid_input(self) -> None:
        with self.assertRaises(RuntimeError):
            calibrator.ratio_from_shifts([0.0, -0.0], 100)

        with self.assertRaises(RuntimeError):
            calibrator.ratio_from_shifts([float("nan")], 100)

        with self.assertRaises(ValueError):
            calibrator.ratio_from_shifts([10.0], 0)

    def test_update_config_file_preserves_existing_fields_and_clamps_ratios(self) -> None:
        config_path = self._temporary_config_path()
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump({"model_id": "yolo12n_cs2", "aim_pixel_ratio_x": 1.0}, handle)

        updated = calibrator.update_config_file(config_path, 0.05, 12.0)

        self.assertEqual(updated["model_id"], "yolo12n_cs2")
        self.assertAlmostEqual(updated["aim_pixel_ratio_x"], 0.1)
        self.assertAlmostEqual(updated["aim_pixel_ratio_y"], 10.0)

        with open(config_path, "r", encoding="utf-8") as handle:
            persisted = json.load(handle)

        self.assertEqual(persisted, updated)

    def test_update_config_file_dry_run_does_not_write_file(self) -> None:
        config_path = self._temporary_config_path()
        original = {"other": True, "aim_pixel_ratio_x": 1.0}
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(original, handle)

        updated = calibrator.update_config_file(config_path, 2.0, 3.0, dry_run=True)

        self.assertAlmostEqual(updated["aim_pixel_ratio_x"], 2.0)
        self.assertAlmostEqual(updated["aim_pixel_ratio_y"], 3.0)
        with open(config_path, "r", encoding="utf-8") as handle:
            persisted = json.load(handle)

        self.assertEqual(persisted, original)

    def test_center_crop_and_gray_conversion_support_rgb_and_gray(self) -> None:
        rgb = np.zeros((10, 20, 3), dtype=np.uint8)
        rgb[:, :, 0] = 10
        rgb[:, :, 1] = 20
        rgb[:, :, 2] = 30

        crop = calibrator.center_crop(rgb, 0.5)
        gray = calibrator.to_gray_float32(crop)

        self.assertEqual(crop.shape, (8, 10, 3))
        self.assertEqual(gray.dtype, np.float32)
        self.assertTrue(gray.flags.c_contiguous)
        self.assertAlmostEqual(float(gray[0, 0]), (0.299 * 10) + (0.587 * 20) + (0.114 * 30), places=5)

        grayscale = np.arange(100, dtype=np.uint8).reshape(10, 10)
        converted = calibrator.to_gray_float32(grayscale)

        self.assertEqual(converted.shape, (10, 10))
        self.assertEqual(converted.dtype, np.float32)

    def test_calibrate_axis_sends_forward_and_reverse_moves_for_x(self) -> None:
        frames = [np.zeros((8, 8), dtype=np.uint8) for _ in range(4)]
        camera = _FakeCamera(frames)
        moves: list[tuple[int, int, str]] = []

        with (
            mock.patch.object(calibrator, "estimate_shift_px", side_effect=[(25.0, 0.0), (-35.0, 0.0)]),
            mock.patch.object(calibrator.time, "sleep", return_value=None),
        ):
            result = calibrator.calibrate_axis(
                "x",
                camera,
                lambda dx, dy, method: moves.append((dx, dy, method)),
                mouse_counts=100,
                samples=2,
                mouse_method="mouse_event",
                settle_s=0.0,
                roi_fraction=0.65,
            )

        self.assertEqual(moves, [(100, 0, "mouse_event"), (-100, 0, "mouse_event")] * 2)
        self.assertEqual(result.axis, "x")
        self.assertEqual(result.samples, (25.0, 35.0))
        self.assertAlmostEqual(result.median_shift_px, 30.0)
        self.assertAlmostEqual(result.ratio, 0.3)

    def test_calibrate_axis_uses_y_shift_for_y_axis(self) -> None:
        frames = [np.zeros((8, 8), dtype=np.uint8) for _ in range(2)]
        camera = _FakeCamera(frames)
        moves: list[tuple[int, int, str]] = []

        with (
            mock.patch.object(calibrator, "estimate_shift_px", return_value=(99.0, -40.0)),
            mock.patch.object(calibrator.time, "sleep", return_value=None),
        ):
            result = calibrator.calibrate_axis(
                "y",
                camera,
                lambda dx, dy, method: moves.append((dx, dy, method)),
                mouse_counts=80,
                samples=1,
                mouse_method="sendinput",
                settle_s=0.0,
                roi_fraction=0.65,
            )

        self.assertEqual(moves, [(0, 80, "sendinput"), (0, -80, "sendinput")])
        self.assertEqual(result.axis, "y")
        self.assertEqual(result.samples, (40.0,))
        self.assertAlmostEqual(result.ratio, 0.5)


if __name__ == "__main__":
    unittest.main()

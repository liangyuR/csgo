import json
import os
import sys
import types
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
        self.stopped = False

    def grab(self):
        if not self._frames:
            raise AssertionError("fake camera ran out of frames")
        return self._frames.pop(0)

    def stop(self):
        self.stopped = True


class CalibrateAimRatioTests(unittest.TestCase):
    def _temporary_config_path(self) -> str:
        path = os.path.join(ROOT, f".tmp_calibrate_config_{uuid.uuid4().hex}.json")
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_ratio_from_shifts_uses_abs_median_mad_and_clamps(self) -> None:
        ratio, samples, median_shift, mad_px = calibrator.ratio_from_shifts([-20.0, 30.0, 40.0], 100)

        self.assertEqual(samples, (20.0, 30.0, 40.0))
        self.assertAlmostEqual(median_shift, 30.0)
        self.assertAlmostEqual(mad_px, 10.0)
        self.assertAlmostEqual(ratio, 0.3)

        low_ratio, _, _, _ = calibrator.ratio_from_shifts([1.0], 100)
        high_ratio, _, _, _ = calibrator.ratio_from_shifts([5000.0], 100)

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

    def test_axis_crop_excludes_lower_band_for_y_axis(self) -> None:
        image = np.arange(100 * 100, dtype=np.uint16).reshape(100, 100)

        x_crop = calibrator.axis_crop(image, 0.5, "x")
        y_crop = calibrator.axis_crop(image, 0.5, "y")

        self.assertEqual(x_crop[0, 0], image[25, 25])
        self.assertEqual(y_crop[0, 0], image[15, 25])
        self.assertLess(y_crop[-1, 0], image[75, 25])

    def test_estimate_shift_px_excludes_lower_band_for_y_axis(self) -> None:
        class FakeCV2:
            CV_32F = 5

            def __init__(self) -> None:
                self.before_gray = None

            def createHanningWindow(self, size, _window_type):
                return np.ones((size[1], size[0]), dtype=np.float32)

            def phaseCorrelate(self, before_gray, _after_gray, _window):
                self.before_gray = before_gray.copy()
                return (1.0, 2.0), 0.9

        fake_cv2 = FakeCV2()
        image = np.arange(100 * 100, dtype=np.uint16).reshape(100, 100)

        with mock.patch.dict(sys.modules, {"cv2": fake_cv2}):
            shift = calibrator.estimate_shift_px(image, image, roi_fraction=0.5, axis="y")

        self.assertIsNotNone(fake_cv2.before_gray)
        self.assertEqual(fake_cv2.before_gray.shape, (50, 50))
        self.assertEqual(float(fake_cv2.before_gray[0, 0]), float(image[15, 25]))
        self.assertEqual(shift, (1.0, 2.0, 0.9))

    def test_grab_fresh_frame_polls_until_frame_arrives(self) -> None:
        frame = np.ones((4, 4), dtype=np.uint8)
        camera = _FakeCamera([None, None, frame])

        with mock.patch.object(calibrator.time, "sleep", return_value=None) as sleep_mock:
            captured = calibrator._grab_fresh_frame(camera, timeout_s=1.0)

        self.assertTrue(np.array_equal(captured, frame))
        self.assertEqual(sleep_mock.call_count, 2)

    def test_calibrate_axis_sends_forward_and_reverse_moves_for_x(self) -> None:
        frames = [np.zeros((8, 8), dtype=np.uint8) for _ in range(6)]
        camera = _FakeCamera(frames)
        moves: list[tuple[int, int, str]] = []

        with (
            mock.patch.object(
                calibrator,
                "estimate_shift_px",
                side_effect=[(25.0, 0.0), (-35.0, 0.0), (45.0, 0.0), (-55.0, 0.0)],
            ),
            mock.patch.object(calibrator.time, "sleep", return_value=None),
        ):
            result = calibrator.calibrate_axis(
                "x",
                camera,
                lambda dx, dy, method: moves.append((dx, dy, method)),
                mouse_counts=100,
                samples=2,
                mouse_method="ddxoft",
                settle_s=0.0,
                roi_fraction=0.65,
                auto_tune=False,
            )

        self.assertEqual(moves, [(100, 0, "ddxoft"), (-100, 0, "ddxoft")] * 2)
        self.assertEqual(result.axis, "x")
        self.assertEqual(result.samples, (25.0, 35.0, 45.0, 55.0))
        self.assertAlmostEqual(result.median_shift_px, 40.0)
        self.assertAlmostEqual(result.mad_px, 10.0)
        self.assertAlmostEqual(result.ratio, 0.4)

    def test_calibrate_axis_uses_y_shift_for_y_axis(self) -> None:
        frames = [np.zeros((8, 8), dtype=np.uint8) for _ in range(3)]
        camera = _FakeCamera(frames)
        moves: list[tuple[int, int, str]] = []

        with (
            mock.patch.object(calibrator, "estimate_shift_px", side_effect=[(5.0, -40.0), (5.0, 50.0)]),
            mock.patch.object(calibrator.time, "sleep", return_value=None),
        ):
            result = calibrator.calibrate_axis(
                "y",
                camera,
                lambda dx, dy, method: moves.append((dx, dy, method)),
                mouse_counts=80,
                samples=1,
                mouse_method="ddxoft",
                settle_s=0.0,
                roi_fraction=0.65,
                auto_tune=False,
            )

        self.assertEqual(moves, [(0, 80, "ddxoft"), (0, -80, "ddxoft")])
        self.assertEqual(result.axis, "y")
        self.assertEqual(result.samples, (40.0, 50.0))
        self.assertAlmostEqual(result.median_shift_px, 45.0)
        self.assertAlmostEqual(result.ratio, 0.5625)

    def test_calibrate_axis_auto_increases_counts_when_shift_too_small(self) -> None:
        frames = [np.zeros((1000, 1000), dtype=np.uint8) for _ in range(6)]
        camera = _FakeCamera(frames)
        moves: list[tuple[int, int, str]] = []

        with (
            mock.patch.object(
                calibrator,
                "estimate_shift_px",
                side_effect=[(2.0, 0.0), (-2.0, 0.0), (20.0, 0.0), (-20.0, 0.0)],
            ),
            mock.patch.object(calibrator.time, "sleep", return_value=None),
        ):
            result = calibrator.calibrate_axis(
                "x",
                camera,
                lambda dx, dy, method: moves.append((dx, dy, method)),
                mouse_counts=50,
                samples=1,
                mouse_method="ddxoft",
                settle_s=0.0,
                roi_fraction=1.0,
            )

        self.assertEqual(moves, [(50, 0, "ddxoft"), (-50, 0, "ddxoft"), (100, 0, "ddxoft"), (-100, 0, "ddxoft")])
        self.assertEqual(result.mouse_counts, 100)
        self.assertEqual(result.samples, (20.0, 20.0))
        self.assertAlmostEqual(result.ratio, 0.2)

    def test_calibrate_axis_auto_decreases_counts_when_shift_too_large(self) -> None:
        frames = [np.zeros((1000, 1000), dtype=np.uint8) for _ in range(6)]
        camera = _FakeCamera(frames)
        moves: list[tuple[int, int, str]] = []

        with (
            mock.patch.object(
                calibrator,
                "estimate_shift_px",
                side_effect=[(900.0, 0.0), (-900.0, 0.0), (100.0, 0.0), (-100.0, 0.0)],
            ),
            mock.patch.object(calibrator.time, "sleep", return_value=None),
        ):
            result = calibrator.calibrate_axis(
                "x",
                camera,
                lambda dx, dy, method: moves.append((dx, dy, method)),
                mouse_counts=100,
                samples=1,
                mouse_method="ddxoft",
                settle_s=0.0,
                roi_fraction=1.0,
            )

        self.assertEqual(moves, [(100, 0, "ddxoft"), (-100, 0, "ddxoft"), (50, 0, "ddxoft"), (-50, 0, "ddxoft")])
        self.assertEqual(result.mouse_counts, 50)
        self.assertEqual(result.samples, (100.0, 100.0))
        self.assertAlmostEqual(result.ratio, 2.0)

    def test_calibrate_axis_rejects_low_response_samples(self) -> None:
        frames = [np.zeros((100, 100), dtype=np.uint8) for _ in range(3)]
        camera = _FakeCamera(frames)

        with (
            mock.patch.object(calibrator, "estimate_shift_px", side_effect=[(30.0, 0.0, 0.1), (-30.0, 0.0, 0.9)]),
            mock.patch.object(calibrator.time, "sleep", return_value=None),
        ):
            result = calibrator.calibrate_axis(
                "x",
                camera,
                lambda _dx, _dy, _method: None,
                mouse_counts=100,
                samples=1,
                mouse_method="ddxoft",
                settle_s=0.0,
                roi_fraction=1.0,
                auto_tune=False,
                min_accepted_samples=1,
            )

        self.assertEqual(result.accepted_samples, 1)
        self.assertEqual(result.rejected_samples, 1)
        self.assertEqual(result.rejection_counts, {"low_response": 1})
        self.assertAlmostEqual(result.ratio, 0.3)

    def test_calibrate_axis_rejects_cross_axis_drift(self) -> None:
        frames = [np.zeros((100, 100), dtype=np.uint8) for _ in range(3)]
        camera = _FakeCamera(frames)

        with (
            mock.patch.object(calibrator, "estimate_shift_px", side_effect=[(30.0, 20.0, 0.9), (-30.0, 0.0, 0.9)]),
            mock.patch.object(calibrator.time, "sleep", return_value=None),
        ):
            result = calibrator.calibrate_axis(
                "x",
                camera,
                lambda _dx, _dy, _method: None,
                mouse_counts=100,
                samples=1,
                mouse_method="ddxoft",
                settle_s=0.0,
                roi_fraction=1.0,
                auto_tune=False,
                max_cross_axis_ratio=0.35,
                min_accepted_samples=1,
            )

        self.assertEqual(result.accepted_samples, 1)
        self.assertEqual(result.rejected_samples, 1)
        self.assertEqual(result.rejection_counts, {"cross_axis": 1})
        self.assertAlmostEqual(result.ratio, 0.3)

    def test_run_calibration_does_not_write_when_samples_are_rejected(self) -> None:
        config_path = self._temporary_config_path()
        original = {"aim_pixel_ratio_x": 1.0, "aim_pixel_ratio_y": 1.0, "mouse_move_method": "ddxoft"}
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(original, handle)

        camera = _FakeCamera([np.zeros((100, 100), dtype=np.uint8) for _ in range(6)])
        fake_win_utils = types.SimpleNamespace(send_mouse_move=lambda _dx, _dy, _method: None)
        args = calibrator.build_parser().parse_args(
            [
                "--config",
                config_path,
                "--samples",
                "1",
                "--validation-samples",
                "0",
                "--mouse-counts",
                "100",
                "--settle-s",
                "0",
                "--warmup-s",
                "0",
                "--countdown",
                "0",
                "--no-auto-tune",
            ]
        )

        with (
            mock.patch.dict(sys.modules, {"win_utils": fake_win_utils}),
            mock.patch.object(calibrator, "create_dxcam_camera", return_value=camera),
            mock.patch.object(calibrator, "estimate_shift_px", side_effect=[(30.0, 0.0, 0.1), (-30.0, 0.0, 0.1)]),
            mock.patch.object(calibrator.time, "sleep", return_value=None),
        ):
            exit_code = calibrator.run_calibration(args)

        self.assertEqual(exit_code, 1)
        with open(config_path, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), original)

    def test_run_calibration_does_not_write_when_validation_fails(self) -> None:
        config_path = self._temporary_config_path()
        original = {"aim_pixel_ratio_x": 1.0, "aim_pixel_ratio_y": 1.0, "mouse_move_method": "ddxoft"}
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(original, handle)

        camera = _FakeCamera([np.zeros((100, 100), dtype=np.uint8) for _ in range(12)])
        fake_win_utils = types.SimpleNamespace(send_mouse_move=lambda _dx, _dy, _method: None)
        args = calibrator.build_parser().parse_args(
            [
                "--config",
                config_path,
                "--samples",
                "1",
                "--validation-samples",
                "1",
                "--mouse-counts",
                "100",
                "--settle-s",
                "0",
                "--warmup-s",
                "0",
                "--countdown",
                "0",
                "--no-auto-tune",
            ]
        )

        with (
            mock.patch.dict(sys.modules, {"win_utils": fake_win_utils}),
            mock.patch.object(calibrator, "create_dxcam_camera", return_value=camera),
            mock.patch.object(
                calibrator,
                "estimate_shift_px",
                side_effect=[
                    (30.0, 0.0, 0.9),
                    (-30.0, 0.0, 0.9),
                    (0.0, 40.0, 0.9),
                    (0.0, -40.0, 0.9),
                    (60.0, 0.0, 0.9),
                    (-60.0, 0.0, 0.9),
                    (0.0, 40.0, 0.9),
                    (0.0, -40.0, 0.9),
                ],
            ),
            mock.patch.object(calibrator.time, "sleep", return_value=None),
        ):
            exit_code = calibrator.run_calibration(args)

        self.assertEqual(exit_code, 1)
        with open(config_path, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), original)

    def test_run_calibration_force_write_persists_after_validation_failure(self) -> None:
        config_path = self._temporary_config_path()
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump({"aim_pixel_ratio_x": 1.0, "aim_pixel_ratio_y": 1.0, "mouse_move_method": "ddxoft"}, handle)

        camera = _FakeCamera([np.zeros((100, 100), dtype=np.uint8) for _ in range(12)])
        fake_win_utils = types.SimpleNamespace(send_mouse_move=lambda _dx, _dy, _method: None)
        args = calibrator.build_parser().parse_args(
            [
                "--config",
                config_path,
                "--samples",
                "1",
                "--validation-samples",
                "1",
                "--mouse-counts",
                "100",
                "--settle-s",
                "0",
                "--warmup-s",
                "0",
                "--countdown",
                "0",
                "--no-auto-tune",
                "--force-write",
            ]
        )

        with (
            mock.patch.dict(sys.modules, {"win_utils": fake_win_utils}),
            mock.patch.object(calibrator, "create_dxcam_camera", return_value=camera),
            mock.patch.object(
                calibrator,
                "estimate_shift_px",
                side_effect=[
                    (30.0, 0.0, 0.9),
                    (-30.0, 0.0, 0.9),
                    (0.0, 40.0, 0.9),
                    (0.0, -40.0, 0.9),
                    (60.0, 0.0, 0.9),
                    (-60.0, 0.0, 0.9),
                    (0.0, 40.0, 0.9),
                    (0.0, -40.0, 0.9),
                ],
            ),
            mock.patch.object(calibrator.time, "sleep", return_value=None),
        ):
            exit_code = calibrator.run_calibration(args)

        self.assertEqual(exit_code, 0)
        with open(config_path, "r", encoding="utf-8") as handle:
            updated = json.load(handle)
        self.assertAlmostEqual(updated["aim_pixel_ratio_x"], 0.3)
        self.assertAlmostEqual(updated["aim_pixel_ratio_y"], 0.4)

    def test_run_calibration_defaults_method_from_config_and_stops_camera(self) -> None:
        config_path = self._temporary_config_path()
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump({"mouse_move_method": "ddxoft"}, handle)

        camera = _FakeCamera([np.zeros((8, 8), dtype=np.uint8) for _ in range(6)])
        moves: list[tuple[int, int, str]] = []
        fake_win_utils = types.SimpleNamespace(send_mouse_move=lambda dx, dy, method: moves.append((dx, dy, method)))
        args = calibrator.build_parser().parse_args(
            [
                "--config",
                config_path,
                "--samples",
                "1",
                "--mouse-counts",
                "100",
                "--settle-s",
                "0",
                "--warmup-s",
                "0",
                "--countdown",
                "0",
                "--no-auto-tune",
                "--validation-samples",
                "0",
            ]
        )

        with (
            mock.patch.dict(sys.modules, {"win_utils": fake_win_utils}),
            mock.patch.object(calibrator, "create_dxcam_camera", return_value=camera),
            mock.patch.object(
                calibrator,
                "estimate_shift_px",
                side_effect=[(30.0, 0.0, 0.9), (-30.0, 0.0, 0.9), (0.0, 40.0, 0.9), (0.0, -40.0, 0.9)],
            ),
            mock.patch.object(calibrator.time, "sleep", return_value=None),
        ):
            exit_code = calibrator.run_calibration(args)

        self.assertEqual(exit_code, 0)
        self.assertTrue(camera.stopped)
        self.assertEqual([method for _, _, method in moves], ["ddxoft"] * 4)
        with open(config_path, "r", encoding="utf-8") as handle:
            updated = json.load(handle)
        self.assertAlmostEqual(updated["aim_pixel_ratio_x"], 0.3)
        self.assertAlmostEqual(updated["aim_pixel_ratio_y"], 0.4)


if __name__ == "__main__":
    unittest.main()

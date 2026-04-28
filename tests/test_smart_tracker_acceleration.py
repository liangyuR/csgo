import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


from core.smart_tracker import SmartTracker


class SmartTrackerAccelerationTests(unittest.TestCase):
    def test_acceleration_prediction_is_opt_in(self) -> None:
        tracker = SmartTracker(velocity_ema_alpha=1.0, velocity_deadzone_px_per_s=0.0)
        tracker.update(0.0, 0.0, 0.1, 96.0)
        tracker.update(10.0, 0.0, 0.1, 96.0)
        tracker.update(30.0, 0.0, 0.1, 96.0)

        default_prediction = tracker.get_predicted_position(0.1, 100.0)
        linear_prediction = tracker.get_predicted_position(0.1, 100.0, use_acceleration=False)
        accelerated_prediction = tracker.get_predicted_position(0.1, 100.0, use_acceleration=True)

        self.assertEqual(default_prediction, linear_prediction)
        self.assertGreater(accelerated_prediction[0], linear_prediction[0])
        self.assertAlmostEqual(accelerated_prediction[1], linear_prediction[1])

    def test_acceleration_resets_on_reverse_motion(self) -> None:
        tracker = SmartTracker(velocity_ema_alpha=1.0, velocity_deadzone_px_per_s=0.0)
        tracker.update(0.0, 0.0, 0.1, 96.0)
        tracker.update(10.0, 0.0, 0.1, 96.0)
        tracker.update(30.0, 0.0, 0.1, 96.0)

        self.assertGreater(tracker.ax, 0.0)

        tracker.update(25.0, 0.0, 0.1, 96.0)

        self.assertLess(tracker.vx, 0.0)
        self.assertEqual(tracker.ax, 0.0)
        self.assertEqual(tracker.ay, 0.0)

    def test_acceleration_prediction_still_respects_distance_cap(self) -> None:
        tracker = SmartTracker(velocity_ema_alpha=1.0, velocity_deadzone_px_per_s=0.0)
        tracker.update(0.0, 0.0, 0.1, 96.0)
        tracker.update(10.0, 0.0, 0.1, 96.0)
        tracker.update(40.0, 0.0, 0.1, 96.0)

        predicted_x, predicted_y = tracker.get_predicted_position(1.0, 12.0, use_acceleration=True)

        self.assertAlmostEqual(predicted_x, 52.0)
        self.assertAlmostEqual(predicted_y, 0.0)


if __name__ == "__main__":
    unittest.main()

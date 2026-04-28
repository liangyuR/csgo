"""Verify the PID controller has no hidden gain remap and is linear in Kp."""

from __future__ import annotations

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


from core.inference import PIDController


class PIDLinearGainTests(unittest.TestCase):
    """Pre-v3 PIDController silently boosted ``Kp`` above 0.5 by 3x. v3 must
    keep the controller fully linear so users can predict the effect of tuning
    a single knob."""

    def test_proportional_output_is_linear_in_kp_below_half(self) -> None:
        a = PIDController(0.4, 0.0, 0.0)
        b = PIDController(0.2, 0.0, 0.0)

        a_out = a.update(10.0, 0.005)
        b_out = b.update(10.0, 0.005)

        self.assertAlmostEqual(a_out, 4.0, places=6)
        self.assertAlmostEqual(b_out, 2.0, places=6)
        self.assertAlmostEqual(a_out / b_out, 2.0, places=6)

    def test_proportional_output_is_linear_in_kp_above_half(self) -> None:
        # Pre-v3 this would have produced 0.5 + (1.0 - 0.5) * 3 = 2.0 instead
        # of 1.0 * error. The migration in migrate_config_data is responsible
        # for preserving user gain; the controller itself must be linear.
        controller = PIDController(1.0, 0.0, 0.0)
        output = controller.update(10.0, 0.005)
        self.assertAlmostEqual(output, 10.0, places=6)

    def test_zero_kp_produces_zero_proportional_output(self) -> None:
        controller = PIDController(0.0, 0.0, 0.0)
        output = controller.update(50.0, 0.005)
        self.assertAlmostEqual(output, 0.0, places=6)

    def test_kp_remap_helper_is_removed(self) -> None:
        controller = PIDController(2.0, 0.0, 0.0)
        self.assertFalse(hasattr(controller, "_calculate_adjusted_kp"))


if __name__ == "__main__":
    unittest.main()

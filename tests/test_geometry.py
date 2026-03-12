import math
import unittest

from src.csgo_vision_demo.geometry import build_detection_geometry, compute_aim_point, select_primary_index


class GeometryTests(unittest.TestCase):
    def test_center_aim_point(self):
        point = compute_aim_point((10, 20, 30, 60), mode="center")
        self.assertEqual(point, (20.0, 40.0))

    def test_upper_center_aim_point(self):
        point = compute_aim_point((10, 20, 30, 120), mode="upper_center", head_fraction=0.2)
        self.assertEqual(point, (20.0, 40.0))

    def test_geometry_distance(self):
        geometry = build_detection_geometry((50, 50, 150, 150), frame_size=(200, 200), mode="center")
        self.assertEqual(geometry.aim_point, (100.0, 100.0))
        self.assertEqual(geometry.offset, (0.0, 0.0))
        self.assertTrue(math.isclose(geometry.distance_to_center, 0.0))

    def test_select_primary_index_prefers_smallest_distance(self):
        g1 = build_detection_geometry((10, 10, 30, 30), frame_size=(200, 200), mode="center")
        g2 = build_detection_geometry((90, 90, 110, 110), frame_size=(200, 200), mode="center")
        g3 = build_detection_geometry((140, 140, 180, 180), frame_size=(200, 200), mode="center")
        self.assertEqual(select_primary_index([g1, g2, g3]), 1)


if __name__ == "__main__":
    unittest.main()

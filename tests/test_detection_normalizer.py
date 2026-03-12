import unittest

from src.csgo_vision_demo.detection_normalizer import extract_detection_records


class _FakeTensor:
    def __init__(self, value):
        self._value = value

    def cpu(self):
        return self

    def tolist(self):
        return self._value


class _FakeBoxes:
    def __init__(self):
        self.xyxy = _FakeTensor([[90, 40, 130, 160]])
        self.conf = _FakeTensor([0.9])
        self.cls = _FakeTensor([0])


class _FakeKeypoints:
    def __init__(self):
        self.xy = _FakeTensor([[[110, 60], [108, 62], [112, 62], [0, 0], [0, 0]]])
        self.conf = _FakeTensor([[0.95, 0.9, 0.9, 0.0, 0.0]])


class _FakeResult:
    def __init__(self):
        self.boxes = _FakeBoxes()
        self.keypoints = _FakeKeypoints()


class _TwoBoxes:
    def __init__(self):
        self.xyxy = _FakeTensor([[10, 40, 50, 160], [90, 40, 130, 160]])
        self.conf = _FakeTensor([0.9, 0.8])
        self.cls = _FakeTensor([0, 0])


class _TwoKeypoints:
    def __init__(self):
        self.xy = _FakeTensor([
            [[20, 60], [18, 62], [22, 62], [0, 0], [0, 0]],
            [[100, 60], [98, 62], [102, 62], [0, 0], [0, 0]],
        ])
        self.conf = _FakeTensor([
            [0.95, 0.9, 0.9, 0.0, 0.0],
            [0.95, 0.9, 0.9, 0.0, 0.0],
        ])


class _TwoResult:
    def __init__(self):
        self.boxes = _TwoBoxes()
        self.keypoints = _TwoKeypoints()


class DetectionNormalizerTests(unittest.TestCase):
    def test_pose_head_normalization_uses_nose(self):
        detections, primary_index = extract_detection_records(
            _FakeResult(),
            frame_shape=(200, 200),
            class_names={0: "person"},
            target_class_names={"person"},
            target_class_ids={0},
            aim_mode="pose_head",
        )
        self.assertEqual(primary_index, 0)
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].aim_source, "nose")
        self.assertEqual(detections[0].aim_x, 110.0)
        self.assertEqual(detections[0].aim_y, 60.0)

    def test_nearest_head_to_center_is_selected(self):
        detections, primary_index = extract_detection_records(
            _TwoResult(),
            frame_shape=(200, 200),
            class_names={0: "person"},
            target_class_names={"person"},
            target_class_ids={0},
            aim_mode="pose_head",
            target_strategy="nearest_head_to_center",
        )
        self.assertEqual(primary_index, 1)
        self.assertTrue(detections[1].is_primary_target)

    def test_low_confidence_keypoints_fall_back_to_upper_center(self):
        result = _FakeResult()
        result.keypoints.conf = _FakeTensor([[0.1, 0.1, 0.1, 0.0, 0.0]])
        detections, _ = extract_detection_records(
            result,
            frame_shape=(200, 200),
            class_names={0: "person"},
            target_class_names={"person"},
            target_class_ids={0},
            aim_mode="pose_head",
            min_keypoint_confidence=0.5,
        )
        self.assertEqual(detections[0].aim_source, "upper_center_fallback")


if __name__ == "__main__":
    unittest.main()

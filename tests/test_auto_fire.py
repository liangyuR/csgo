import os
import queue
import sys
import types
import unittest
from types import SimpleNamespace


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


_clicks: list[str] = []


def _record_click(method: str = "mouse_event") -> None:
    _clicks.append(method)


fake_win_utils = types.ModuleType("win_utils")
fake_win_utils.__path__ = []
fake_win_utils.is_key_pressed = lambda _key: False
fake_win_utils.send_mouse_click = _record_click
fake_win_utils.send_mouse_move = lambda dx, dy, method="mouse_event": None
fake_key_utils = types.ModuleType("win_utils.key_utils")
fake_key_utils.is_key_pressed = fake_win_utils.is_key_pressed
fake_win_utils.key_utils = fake_key_utils
sys.modules["win_utils"] = fake_win_utils
sys.modules["win_utils.key_utils"] = fake_key_utils


from core.auto_fire import AutoFireState, _run_auto_fire_step
from core.detection_state import DetectionPayload


class AutoFireTests(unittest.TestCase):
    def setUp(self) -> None:
        _clicks.clear()

    def _make_config(self, **overrides):
        defaults = {
            "auto_fire_key": 1,
            "auto_fire_key2": None,
            "always_auto_fire": True,
            "auto_fire_delay": 0.0,
            "auto_fire_interval": 0.0,
            "crosshairX": 100,
            "crosshairY": 100,
            "mouse_click_method": "mouse_event",
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _hit_payload(self) -> DetectionPayload:
        return DetectionPayload([[95.0, 95.0, 105.0, 105.0]], [0.9], [0])

    def _miss_payload(self) -> DetectionPayload:
        return DetectionPayload([[120.0, 120.0, 130.0, 130.0]], [0.9], [0])

    def test_auto_fire_drains_to_latest_payload_each_tick(self) -> None:
        config = self._make_config()
        state = AutoFireState()
        boxes_queue: queue.Queue = queue.Queue()
        boxes_queue.put((self._miss_payload(), 1.000))
        boxes_queue.put((self._hit_payload(), 1.001))

        fired = _run_auto_fire_step(config, boxes_queue, state, 1.002, click_func=_record_click)

        self.assertTrue(fired)
        self.assertEqual(_clicks, ["mouse_event"])
        self.assertTrue(boxes_queue.empty())

    def test_auto_fire_rejects_stale_payload(self) -> None:
        config = self._make_config()
        state = AutoFireState()
        boxes_queue: queue.Queue = queue.Queue()
        boxes_queue.put((self._hit_payload(), 1.000))

        fired = _run_auto_fire_step(config, boxes_queue, state, 1.041, click_func=_record_click)

        self.assertFalse(fired)
        self.assertEqual(_clicks, [])

    def test_auto_fire_can_fire_again_before_old_sixty_hz_tick_when_interval_allows(self) -> None:
        config = self._make_config(auto_fire_interval=0.003)
        state = AutoFireState()
        boxes_queue: queue.Queue = queue.Queue()
        boxes_queue.put((self._hit_payload(), 1.000))

        first = _run_auto_fire_step(config, boxes_queue, state, 1.000, click_func=_record_click)
        boxes_queue.put((self._hit_payload(), 1.004))
        second = _run_auto_fire_step(config, boxes_queue, state, 1.004, click_func=_record_click)

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(_clicks, ["mouse_event", "mouse_event"])

    def test_auto_fire_interval_still_limits_repeat_fire(self) -> None:
        config = self._make_config(auto_fire_interval=0.08)
        state = AutoFireState()
        boxes_queue: queue.Queue = queue.Queue()
        boxes_queue.put((self._hit_payload(), 1.000))

        first = _run_auto_fire_step(config, boxes_queue, state, 1.000, click_func=_record_click)
        boxes_queue.put((self._hit_payload(), 1.010))
        second = _run_auto_fire_step(config, boxes_queue, state, 1.010, click_func=_record_click)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(_clicks, ["mouse_event"])


if __name__ == "__main__":
    unittest.main()

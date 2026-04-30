import importlib.util
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MODULE_PATH = os.path.join(ROOT, "src", "win_utils", "mouse_move_blocker.py")

spec = importlib.util.spec_from_file_location("mouse_move_blocker_under_test", MODULE_PATH)
mouse_move_blocker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mouse_move_blocker
spec.loader.exec_module(mouse_move_blocker)


class MouseMoveBlockerTests(unittest.TestCase):
    def _make_blocker(self):
        blocker = mouse_move_blocker.MouseMoveBlocker()
        blocker.start = lambda: True
        return blocker

    def test_inactive_blocker_does_not_block_mouse_move(self) -> None:
        blocker = self._make_blocker()

        self.assertFalse(
            blocker.should_block_event(
                mouse_move_blocker.HC_ACTION,
                mouse_move_blocker.WM_MOUSEMOVE,
                flags=0,
                now=1.0,
            )
        )

    def test_active_blocker_blocks_physical_mouse_move(self) -> None:
        blocker = self._make_blocker()
        blocker.set_blocked(True)

        self.assertTrue(
            blocker.should_block_event(
                mouse_move_blocker.HC_ACTION,
                mouse_move_blocker.WM_MOUSEMOVE,
                flags=0,
                now=1.0,
            )
        )

    def test_active_blocker_does_not_block_click_or_injected_move(self) -> None:
        blocker = self._make_blocker()
        blocker.set_blocked(True)

        self.assertFalse(
            blocker.should_block_event(
                mouse_move_blocker.HC_ACTION,
                0x0201,
                flags=0,
                now=1.0,
            )
        )
        self.assertFalse(
            blocker.should_block_event(
                mouse_move_blocker.HC_ACTION,
                mouse_move_blocker.WM_MOUSEMOVE,
                flags=mouse_move_blocker.LLMHF_INJECTED,
                now=1.0,
            )
        )

    def test_program_move_allow_window_bypasses_blocker(self) -> None:
        blocker = self._make_blocker()
        blocker.set_blocked(True)
        blocker._allow_program_move_until = 10.0

        self.assertFalse(
            blocker.should_block_event(
                mouse_move_blocker.HC_ACTION,
                mouse_move_blocker.WM_MOUSEMOVE,
                flags=0,
                now=5.0,
            )
        )
        self.assertTrue(
            blocker.should_block_event(
                mouse_move_blocker.HC_ACTION,
                mouse_move_blocker.WM_MOUSEMOVE,
                flags=0,
                now=11.0,
            )
        )


if __name__ == "__main__":
    unittest.main()

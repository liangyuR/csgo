import unittest

from src.csgo_vision_demo.hotkey import _key_to_vk


class HotkeyTests(unittest.TestCase):
    def test_function_key_mapping(self):
        self.assertEqual(_key_to_vk("f2"), 0x71)

    def test_named_key_mapping(self):
        self.assertEqual(_key_to_vk("caps lock"), 0x14)

    def test_single_character_mapping(self):
        self.assertEqual(_key_to_vk("x"), ord("X"))


if __name__ == "__main__":
    unittest.main()

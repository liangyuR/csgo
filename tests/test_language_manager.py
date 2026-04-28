import json
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


from core.language_manager import LanguageManager


class LanguageManagerTests(unittest.TestCase):
    def _manager(self) -> LanguageManager:
        manager = LanguageManager.__new__(LanguageManager)
        manager.translations = {
            "Chinese_Simplified": {"hello": "你好"},
            "English_English": {"hello": "Hello", "fallback": "Fallback"},
        }
        manager.current_language = manager.DEFAULT_LANGUAGE
        manager.language_dir_path = ""
        return manager

    def test_default_language_is_chinese_simplified(self) -> None:
        manager = self._manager()
        self.assertEqual(manager.DEFAULT_LANGUAGE, "Chinese_Simplified")
        self.assertEqual(manager.get_current_language(), "Chinese_Simplified")

    def test_legacy_chinese_names_normalize_to_chinese_simplified(self) -> None:
        manager = self._manager()
        for legacy_name in ("zh_cn", "zh_tw", "Chinese_中文", "Chinese_ä¸­æ–‡"):
            self.assertEqual(manager._normalize_language_name(legacy_name), "Chinese_Simplified")

    def test_missing_key_falls_back_to_english_then_default(self) -> None:
        manager = self._manager()
        self.assertEqual(manager.get_text("fallback"), "Fallback")
        self.assertEqual(manager.get_text("missing", "Default"), "Default")

    def test_simplified_chinese_resource_matches_english_keys(self) -> None:
        language_dir = os.path.join(SRC_DIR, "core", "language_data")
        with open(os.path.join(language_dir, "English_English.json"), encoding="utf-8") as handle:
            english = json.load(handle)
        with open(os.path.join(language_dir, "Chinese_Simplified.json"), encoding="utf-8") as handle:
            chinese = json.load(handle)
        self.assertEqual(set(english), set(chinese))


if __name__ == "__main__":
    unittest.main()

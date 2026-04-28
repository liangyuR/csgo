"""Language loading and runtime translation helpers."""

from __future__ import annotations

import glob
import json
import os
from typing import Dict, List


class LanguageManager:
    """Load JSON language packs and track the active UI language."""

    DEFAULT_LANGUAGE = "Chinese_Simplified"
    FALLBACK_LANGUAGE = "English_English"
    CONFIG_FILE = "config.json"
    LANGUAGE_DIR = "language_data"

    LEGACY_MAPPING = {
        "zh": DEFAULT_LANGUAGE,
        "zh_cn": DEFAULT_LANGUAGE,
        "zh-cn": DEFAULT_LANGUAGE,
        "zh_hans": DEFAULT_LANGUAGE,
        "zh-hans": DEFAULT_LANGUAGE,
        "zh_tw": DEFAULT_LANGUAGE,
        "zh-tw": DEFAULT_LANGUAGE,
        "zh_hant": DEFAULT_LANGUAGE,
        "zh-hant": DEFAULT_LANGUAGE,
        "Chinese_中文": DEFAULT_LANGUAGE,
        "Chinese_ä¸­æ–‡": DEFAULT_LANGUAGE,
        "en": FALLBACK_LANGUAGE,
        "de": "German_Deutsch",
        "es": "Spanish_Español",
        "fr": "French_Français",
        "hi": "Hindi_हिन्दी",
        "ja": "Japanese_日本語",
        "ko": "Korean_한국어",
        "pt": "Portuguese_Português",
        "ru": "Russian_Русский",
    }

    def __init__(self) -> None:
        self.translations: Dict[str, Dict[str, str]] = {}
        self.current_language: str = self.DEFAULT_LANGUAGE
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.language_dir_path = os.path.join(base_dir, self.LANGUAGE_DIR)
        self.load_all_languages()
        self.load_language_config()

    def _normalize_language_name(self, language_name: str | None) -> str:
        if not language_name:
            return self.DEFAULT_LANGUAGE
        if language_name in self.LEGACY_MAPPING:
            return self.LEGACY_MAPPING[language_name]
        lowered = language_name.lower()
        if lowered in self.LEGACY_MAPPING:
            return self.LEGACY_MAPPING[lowered]
        if language_name.startswith("Chinese_") and language_name != self.DEFAULT_LANGUAGE:
            return self.DEFAULT_LANGUAGE
        return language_name

    def load_all_languages(self) -> None:
        self.translations.clear()

        if not os.path.exists(self.language_dir_path):
            os.makedirs(self.language_dir_path, exist_ok=True)
            return

        json_pattern = os.path.join(self.language_dir_path, "*.json")
        for file_path in glob.glob(json_pattern):
            lang_name = os.path.splitext(os.path.basename(file_path))[0]
            normalized_name = self._normalize_language_name(lang_name)
            if normalized_name == self.DEFAULT_LANGUAGE and lang_name != self.DEFAULT_LANGUAGE:
                continue
            try:
                with open(file_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    self.translations[normalized_name] = data
            except Exception as exc:
                print(f"Error loading language file {os.path.basename(file_path)}: {exc}")

        if self.DEFAULT_LANGUAGE not in self.translations and self.translations:
            self.DEFAULT_LANGUAGE = (
                self.FALLBACK_LANGUAGE
                if self.FALLBACK_LANGUAGE in self.translations
                else next(iter(self.translations))
            )

    def get_text(self, key: str, default: str = "") -> str:
        lang_table = self.translations.get(self.current_language, {})
        if key in lang_table:
            return lang_table[key]

        default_table = self.translations.get(self.DEFAULT_LANGUAGE, {})
        if key in default_table:
            return default_table[key]

        fallback_table = self.translations.get(self.FALLBACK_LANGUAGE, {})
        if key in fallback_table:
            return fallback_table[key]

        return default or key

    def set_language(self, language_name: str) -> bool:
        normalized = self._normalize_language_name(language_name)
        if normalized in self.translations:
            self.current_language = normalized
            self.save_language_config()
            return True
        return False

    def get_current_language(self) -> str:
        return self.current_language

    def get_available_languages(self) -> List[str]:
        languages = list(self.translations.keys())
        if self.DEFAULT_LANGUAGE in languages:
            languages.remove(self.DEFAULT_LANGUAGE)
            languages.insert(0, self.DEFAULT_LANGUAGE)
        return languages

    def save_language_config(self) -> None:
        try:
            config_data = {}
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as handle:
                    config_data = json.load(handle)
            config_data["language"] = self.current_language
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as handle:
                json.dump(config_data, handle, ensure_ascii=False, indent=2)
        except Exception as exc:  # pragma: no cover
            print(f"Failed to save language config: {exc}")

    def load_language_config(self) -> None:
        try:
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as handle:
                    config_data = json.load(handle)
                stored_lang = self._normalize_language_name(config_data.get("language", self.DEFAULT_LANGUAGE))
                self.current_language = stored_lang if stored_lang in self.translations else self.DEFAULT_LANGUAGE
            else:
                self.current_language = self.DEFAULT_LANGUAGE
        except Exception as exc:  # pragma: no cover
            print(f"Failed to load language config: {exc}")
            self.current_language = self.DEFAULT_LANGUAGE


language_manager = LanguageManager()


def get_text(key: str, default: str = "") -> str:
    return language_manager.get_text(key, default)


def set_language(language_code: str) -> bool:
    return language_manager.set_language(language_code)

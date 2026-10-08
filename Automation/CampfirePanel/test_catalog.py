"""Validate the standalone translation catalog without loading Unreal."""

import json
from pathlib import Path
from string import Formatter
import unittest


LANGUAGES = [
    "en", "fr", "de", "it", "es", "ru", "ja", "zh", "ko",
    "tr", "pt", "pl", "ua", "cs", "hu", "zh-tw", "es-mx",
]
PLACEHOLDERS = {
    "title": set(),
    "refill": set(),
    "refill_all": set(),
    "searching": set(),
    "failed": set(),
    "summary": {"count", "wood"},
    "row_name": {"number"},
}


class CatalogTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).with_name("translations.json")
        self.assertTrue(path.is_file(), "The translation catalog is missing")
        self.catalog = json.loads(path.read_text(encoding="utf-8"))

    def test_native_language_ids_and_order(self):
        self.assertEqual(self.catalog["languages"], LANGUAGES)
        self.assertNotIn("nl", self.catalog["languages"])

    def test_complete_nonempty_translations(self):
        strings = self.catalog["strings"]
        self.assertEqual(set(strings), set(PLACEHOLDERS))
        for key, values in strings.items():
            with self.subTest(key=key):
                self.assertIsInstance(values, list)
                self.assertEqual(len(values), len(LANGUAGES))
            for language, value in zip(LANGUAGES, values):
                with self.subTest(key=key, language=language):
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip())
                    self.assertEqual(value, value.strip())

    def test_templates_preserve_named_placeholders(self):
        formatter = Formatter()
        for key, values in self.catalog["strings"].items():
            for language, value in zip(LANGUAGES, values):
                with self.subTest(key=key, language=language):
                    fields = {
                        field for _, field, _, _ in formatter.parse(value)
                        if field is not None
                    }
                    self.assertEqual(fields, PLACEHOLDERS[key])
                    rendered = value.format(count=12, wood=34, number=56)
                    self.assertTrue(rendered)
                    for field in PLACEHOLDERS[key]:
                        expected = {"count": "12", "wood": "34", "number": "56"}[field]
                        self.assertIn(expected, rendered)

    def test_regional_catalogs_are_independently_translated(self):
        strings = self.catalog["strings"]
        for base, regional in (("zh", "zh-tw"), ("es", "es-mx")):
            with self.subTest(language=regional):
                base_values = [values[LANGUAGES.index(base)] for values in strings.values()]
                regional_values = [values[LANGUAGES.index(regional)] for values in strings.values()]
                self.assertNotEqual(base_values, regional_values)


if __name__ == "__main__":
    unittest.main()

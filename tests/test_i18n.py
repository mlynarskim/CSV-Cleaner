from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from csv_cleaner.core.cleaner import clean_data
from csv_cleaner.core.report_generator import build_report, save_reports
from csv_cleaner.i18n import ENGLISH, POLISH, translate
from csv_cleaner.models.cleaning_config import CleaningConfig


class TranslationTests(unittest.TestCase):
    def test_both_languages_have_the_same_keys(self) -> None:
        self.assertEqual(set(ENGLISH), set(POLISH))

    def test_translates_interface_text(self) -> None:
        self.assertEqual(translate("en", "file.choose"), "Choose file")
        self.assertEqual(translate("pl", "file.choose"), "Wybierz plik")

    def test_change_records_are_localized_at_display_time(self) -> None:
        frame = pd.DataFrame({"name": ["  Anna  "]})
        result = clean_data(frame, CleaningConfig(trim_whitespace=True))
        operation_key = result.changes[0].operation
        self.assertEqual(translate("en", operation_key), "Whitespace cleaned")
        self.assertEqual(translate("pl", operation_key), "Czyszczenie odstępów")

    def test_report_uses_selected_language(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.csv"
            result = clean_data(
                pd.DataFrame({"name": ["  Anna  "]}),
                CleaningConfig(trim_whitespace=True),
            )
            report = build_report(
                "source.csv",
                output,
                1,
                1,
                result,
                language="pl",
            )
            text_path, _ = save_reports(report, output)
            content = text_path.read_text(encoding="utf-8")
            self.assertIn("CSV Cleaner: raport operacji", content)
            self.assertIn("Wartości z oczyszczonymi odstępami", content)


if __name__ == "__main__":
    unittest.main()

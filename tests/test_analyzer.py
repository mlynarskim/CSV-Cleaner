from __future__ import annotations

import unittest

import pandas as pd

from csv_cleaner.core.analyzer import analyze_data


class AnalyzerTests(unittest.TestCase):
    def test_detects_core_quality_issues(self) -> None:
        frame = pd.DataFrame(
            {
                "name": [" Anna ", " Anna ", None, "   "],
                "email": ["good@example.com", "good@example.com", "bad address", "   "],
                "empty": [None, None, None, None],
            }
        )
        result = analyze_data(frame)
        self.assertEqual(result.issue("empty_rows").count, 1)
        self.assertEqual(result.issue("empty_columns").columns, ["empty"])
        self.assertEqual(result.issue("duplicates").count, 2)
        self.assertGreater(result.issue("whitespace").count, 0)
        self.assertEqual(result.issue("invalid_emails").count, 1)

    def test_detects_date_column(self) -> None:
        frame = pd.DataFrame({"Data sprzedaży": ["31.01.2026", "2026/02/01", "03/02/2026"]})
        result = analyze_data(frame)
        self.assertIn("Data sprzedaży", result.date_columns)

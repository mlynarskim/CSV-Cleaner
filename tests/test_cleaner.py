from __future__ import annotations

import unittest

import pandas as pd

from csv_cleaner.core.cleaner import clean_data
from csv_cleaner.models.cleaning_config import CleaningConfig, DuplicateConfig


class CleanerTests(unittest.TestCase):
    def test_removes_empty_rows_columns_and_duplicates(self) -> None:
        frame = pd.DataFrame(
            {
                "name": ["Anna", "Anna", "   "],
                "empty": [None, None, None],
            }
        )
        config = CleaningConfig(
            remove_empty_rows=True,
            remove_empty_columns=True,
            duplicates=DuplicateConfig(enabled=True, keep="first"),
        )
        result = clean_data(frame, config)
        self.assertEqual(len(result.data), 1)
        self.assertEqual(list(result.data.columns), ["name"])
        self.assertEqual(result.removed_rows, 2)
        self.assertEqual(result.removed_columns, 1)

    def test_trims_only_text_values(self) -> None:
        frame = pd.DataFrame({"text": ["  Ala   ma kota  "], "number": [10]})
        result = clean_data(
            frame,
            CleaningConfig(trim_whitespace=True, collapse_internal_spaces=True),
        )
        self.assertEqual(result.data.iloc[0]["text"], "Ala ma kota")
        self.assertEqual(result.data.iloc[0]["number"], 10)

    def test_removes_duplicates_by_selected_columns(self) -> None:
        frame = pd.DataFrame({"id": [1, 1, 2], "value": ["a", "b", "c"]})
        config = CleaningConfig(
            duplicates=DuplicateConfig(enabled=True, columns=["id"], keep="last")
        )
        result = clean_data(frame, config)
        self.assertEqual(result.data["value"].tolist(), ["b", "c"])

    def test_standardizes_unique_column_names(self) -> None:
        frame = pd.DataFrame([[1, 2]], columns=[" Data sprzedaży ", "Data sprzedaży"])
        config = CleaningConfig(
            standardize_column_names=True,
            remove_polish_characters=True,
        )
        result = clean_data(frame, config)
        self.assertEqual(list(result.data.columns), ["data_sprzedazy", "data_sprzedazy_2"])

    def test_converts_dates_and_keeps_invalid_values(self) -> None:
        frame = pd.DataFrame({"date": ["31/01/2026", "not a date"]})
        config = CleaningConfig(date_columns=["date"], date_output_format="%Y.%m.%d")
        result = clean_data(frame, config)
        self.assertEqual(result.data.iloc[0]["date"], "2026.01.31")
        self.assertEqual(result.data.iloc[1]["date"], "not a date")
        self.assertEqual(len(result.warnings), 1)

    def test_fills_missing_values(self) -> None:
        frame = pd.DataFrame({"amount": [1.0, None, 3.0]})
        config = CleaningConfig(
            missing_strategy="mean",
            missing_columns=["amount"],
        )
        result = clean_data(frame, config)
        self.assertEqual(result.data.iloc[1]["amount"], 2.0)

    def test_does_not_modify_source_frame(self) -> None:
        frame = pd.DataFrame({"name": ["  Anna  "]})
        original = frame.copy(deep=True)
        clean_data(frame, CleaningConfig(trim_whitespace=True))
        pd.testing.assert_frame_equal(frame, original)

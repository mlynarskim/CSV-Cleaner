from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from csv_cleaner.core.file_loader import FileLoadError, load_file


class FileLoaderTests(unittest.TestCase):
    def test_loads_semicolon_csv_and_detects_separator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.csv"
            path.write_text("name;city\nAnna;Kraków\n", encoding="utf-8")
            loaded = load_file(path)
            self.assertEqual(loaded.separator, ";")
            self.assertEqual(loaded.data.iloc[0]["city"], "Kraków")

    def test_loads_cp1250_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.csv"
            path.write_bytes("imię;miasto\nŁukasz;Łódź\n".encode("cp1250"))
            loaded = load_file(path, separator=";")
            self.assertEqual(loaded.encoding, "cp1250")
            self.assertEqual(loaded.data.iloc[0]["imię"], "Łukasz")

    def test_loads_selected_excel_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.xlsx"
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="Pierwszy", index=False)
                pd.DataFrame({"b": [2]}).to_excel(writer, sheet_name="Drugi", index=False)
            loaded = load_file(path, sheet_name="Drugi")
            self.assertEqual(loaded.sheet_name, "Drugi")
            self.assertEqual(list(loaded.data.columns), ["b"])

    def test_rejects_unsupported_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_text("data", encoding="utf-8")
            with self.assertRaises(FileLoadError):
                load_file(path)

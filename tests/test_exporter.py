from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from csv_cleaner.core.exporter import ExportError, export_data
from csv_cleaner.core.report_generator import build_report, save_reports
from csv_cleaner.models.operation_result import OperationResult


class ExporterTests(unittest.TestCase):
    def test_exports_csv_without_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.csv"
            export_data(pd.DataFrame({"name": ["Łukasz"]}), path, separator=";")
            content = path.read_text(encoding="utf-8-sig")
            self.assertEqual(content, "name\nŁukasz\n".replace("\n", ";\n", 0))
            self.assertNotIn("Unnamed", content)

    def test_exports_xlsx(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.xlsx"
            export_data(pd.DataFrame({"value": [7]}), path)
            restored = pd.read_excel(path)
            self.assertEqual(restored.iloc[0]["value"], 7)

    def test_refuses_overwrite_without_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.csv"
            path.write_text("existing", encoding="utf-8")
            with self.assertRaises(ExportError):
                export_data(pd.DataFrame({"value": [1]}), path)
            self.assertEqual(path.read_text(encoding="utf-8"), "existing")

    def test_generates_txt_and_json_reports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.csv"
            result = OperationResult(data=pd.DataFrame({"value": [1]}))
            result.operations["trimmed_values"] = 2
            report = build_report("source.csv", output, 1, 1, result)
            text_path, json_path = save_reports(report, output)
            self.assertTrue(text_path.exists())
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["source_file"], "source.csv")

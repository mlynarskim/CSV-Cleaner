from __future__ import annotations

import tkinter as tk
import unittest

from csv_cleaner.ui.main_window import parse_dropped_paths


class DragDropTests(unittest.TestCase):
    def test_parses_paths_with_spaces_and_multiple_files(self) -> None:
        interpreter = tk.Tcl()
        paths = parse_dropped_paths(
            "{/tmp/My File.csv} /tmp/second.xlsx",
            interpreter.splitlist,
        )
        self.assertEqual(str(paths[0]), "/tmp/My File.csv")
        self.assertEqual(str(paths[1]), "/tmp/second.xlsx")

    def test_ignores_empty_drop_data(self) -> None:
        interpreter = tk.Tcl()
        self.assertEqual(parse_dropped_paths("", interpreter.splitlist), [])

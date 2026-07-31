from __future__ import annotations

import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from csv_cleaner.ui.main_window import MainWindow  # noqa: E402


SAMPLE_FILE = PROJECT_DIR / "sample_data" / "dirty_sample.csv"


def wait_for_idle(app: MainWindow, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while app.is_busy and time.monotonic() < deadline:
        app.update()
        time.sleep(0.01)
    if app.is_busy:
        raise AssertionError("The interface did not finish in time.")
    app.update()


def find_button(app: MainWindow, text: str):
    for button in app._all_buttons():
        if button.cget("text") == text:
            return button
    raise AssertionError(f"Button not found: {text}")


def click_button(app: MainWindow, button) -> None:
    app.update()
    x = max(2, button.winfo_width() // 2)
    y = max(2, button.winfo_height() // 2)
    button.event_generate("<Enter>", x=x, y=y)
    button.event_generate("<ButtonPress-1>", x=x, y=y)
    app.update()
    button.event_generate("<ButtonRelease-1>", x=x, y=y)
    app.update()


def assert_step(app: MainWindow, expected: str) -> None:
    current = str(app.step_label.cget("text"))
    if expected not in current:
        raise AssertionError(f"Oczekiwano etapu {expected}, otrzymano: {current}")


def run_smoke_test() -> None:
    app = MainWindow()
    app.update()
    try:
        if sys.platform == "darwin":
            theme = app.tk.call("ttk::style", "theme", "use")
            if theme == "clam":
                raise AssertionError("The clam theme must not be forced on macOS.")

        if app.progress.winfo_ismapped():
            raise AssertionError("The progress indicator is visible while idle.")

        assert_step(app, "Step 1 of 5")
        find_button(app, "Choose file")
        app.language_var.set("pl")
        app._change_language()
        assert_step(app, "Etap 1 z 5")
        find_button(app, "Wybierz plik")
        app.language_var.set("en")
        app._change_language()
        assert_step(app, "Step 1 of 5")

        app._load(str(SAMPLE_FILE))
        wait_for_idle(app)
        assert_step(app, "Step 2 of 5")
        if app.sheet_combo.winfo_ismapped():
            raise AssertionError("The sheet field is visible for a CSV file.")
        if not app.encoding_combo.winfo_ismapped():
            raise AssertionError("The encoding field is hidden for a CSV file.")

        app.encoding_combo.current(0)
        app.separator_combo.set("Semicolon")
        click_button(app, find_button(app, "Apply settings"))
        wait_for_idle(app)
        if app.separator_var.get() != "Semicolon":
            raise AssertionError("The selected separator was not preserved.")

        app.language_var.set("pl")
        app._change_language()
        if app.separator_var.get() != "Średnik":
            raise AssertionError("The separator was not translated to Polish.")
        if app.loaded is None:
            raise AssertionError("Changing language cleared the loaded file.")
        app.language_var.set("en")
        app._change_language()
        if app.separator_var.get() != "Semicolon":
            raise AssertionError("The separator was not translated to English.")

        click_button(app, app.analyze_button)
        wait_for_idle(app)
        assert_step(app, "Step 3 of 5")

        app.update()
        before_scroll = app.analysis_scroll.canvas.yview()
        scroll_event = SimpleNamespace(
            delta=-1,
            x_root=app.analysis_scroll.winfo_rootx() + 30,
            y_root=app.analysis_scroll.winfo_rooty() + 30,
        )
        app.analysis_scroll._on_mousewheel(scroll_event)
        app.update()
        after_scroll = app.analysis_scroll.canvas.yview()
        if before_scroll == after_scroll:
            raise AssertionError("Scrolling did not change the settings position.")

        click_button(app, find_button(app, "Back to data"))
        assert_step(app, "Step 2 of 5")
        click_button(app, app.analyze_button)
        wait_for_idle(app)

        click_button(app, app.preview_button)
        wait_for_idle(app)
        assert_step(app, "Step 4 of 5")

        click_button(app, find_button(app, "Back to settings"))
        assert_step(app, "Step 3 of 5")
        click_button(app, app.preview_button)
        wait_for_idle(app)

        click_button(app, find_button(app, "Discard changes"))
        assert_step(app, "Step 3 of 5")
        click_button(app, app.preview_button)
        wait_for_idle(app)

        click_button(app, app.approve_button)
        assert_step(app, "Step 5 of 5")
        if app.xlsx_export_options.winfo_ismapped():
            raise AssertionError("Excel options are visible for a CSV output.")

        app.output_path_var.set(str(PROJECT_DIR / "temporary_test.xlsx"))
        app.update()
        if not app.xlsx_export_options.winfo_ismapped():
            raise AssertionError("Excel options are hidden for an XLSX output.")
        if app.csv_export_options.winfo_ismapped():
            raise AssertionError("CSV options are visible for an XLSX output.")

        click_button(app, find_button(app, "Back to preview"))
        assert_step(app, "Step 4 of 5")
        click_button(app, app.approve_button)

        with TemporaryDirectory() as directory:
            output = Path(directory) / "result.csv"
            app.output_path_var.set(str(output))
            with patch("csv_cleaner.ui.main_window.messagebox.showinfo"):
                click_button(app, app.save_button)
                wait_for_idle(app)
            if not output.exists():
                raise AssertionError("The save button did not create a file.")
            if not app.last_reports or not all(path.exists() for path in app.last_reports):
                raise AssertionError("The save button did not create reports.")
            report_text = app.last_reports[0].read_text(encoding="utf-8")
            if "CSV Cleaner operation report" not in report_text:
                raise AssertionError("The TXT report is not in English.")

            opened: list[Path] = []
            app._open_path = opened.append  # type: ignore[method-assign]
            click_button(app, app.open_report_button)
            click_button(app, app.open_folder_button)
            if len(opened) != 2:
                raise AssertionError("Report and folder buttons did not work.")

        with TemporaryDirectory() as directory:
            workbook = Path(directory) / "sheets.xlsx"
            with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
                pd.DataFrame({"first": [1]}).to_excel(
                    writer,
                    sheet_name="Pierwszy",
                    index=False,
                )
                pd.DataFrame({"second": [2]}).to_excel(
                    writer,
                    sheet_name="Drugi",
                    index=False,
                )
            app._load(str(workbook))
            wait_for_idle(app)
            if not app.sheet_combo.winfo_ismapped():
                raise AssertionError("The sheet field is hidden for an XLSX file.")
            if app.encoding_combo.winfo_ismapped():
                raise AssertionError("The encoding field is visible for XLSX.")
            app.sheet_combo.set("Drugi")
            click_button(app, find_button(app, "Apply settings"))
            wait_for_idle(app)
            if app.loaded is None or app.loaded.sheet_name != "Drugi":
                raise AssertionError("The selected sheet was not loaded.")

        for button in app._all_buttons():
            if not str(button.cget("command")):
                raise AssertionError(
                    f"Button without a command: {button.cget('text')}"
                )

        app._set_busy("Testing progress…", True)
        if not app.progress.winfo_ismapped():
            raise AssertionError("The progress indicator did not appear.")
        if any(not button.instate(["disabled"]) for button in app._all_buttons()):
            raise AssertionError("Not all buttons were disabled.")
        app._set_busy("", False)
        if app.progress.winfo_ismapped():
            raise AssertionError("The progress indicator was not hidden.")
    finally:
        app.unsaved_changes = False
        app.destroy()


if __name__ == "__main__":
    run_smoke_test()
    print("Interface smoke test completed successfully.")

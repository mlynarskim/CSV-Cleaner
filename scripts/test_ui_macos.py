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
        raise AssertionError("Interfejs nie zakończył operacji w oczekiwanym czasie.")
    app.update()


def find_button(app: MainWindow, text: str):
    for button in app._all_buttons():
        if button.cget("text") == text:
            return button
    raise AssertionError(f"Nie znaleziono przycisku: {text}")


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
                raise AssertionError("Na macOS nie powinien być wymuszany motyw clam.")

        if app.progress.winfo_ismapped():
            raise AssertionError("Wskaźnik postępu jest widoczny podczas bezczynności.")

        app._load(str(SAMPLE_FILE))
        wait_for_idle(app)
        assert_step(app, "Etap 2 z 5")
        if app.sheet_combo.winfo_ismapped():
            raise AssertionError("Pole arkusza jest widoczne dla pliku CSV.")
        if not app.encoding_combo.winfo_ismapped():
            raise AssertionError("Pole kodowania nie jest widoczne dla pliku CSV.")

        app.encoding_combo.current(0)
        app.separator_combo.set("Średnik")
        click_button(app, find_button(app, "Zastosuj ustawienia"))
        wait_for_idle(app)
        if app.separator_var.get() != "Średnik":
            raise AssertionError("Nie zachowano wybranego separatora.")

        click_button(app, app.analyze_button)
        wait_for_idle(app)
        assert_step(app, "Etap 3 z 5")

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
            raise AssertionError("Przewijanie ustawień nie zmieniło pozycji.")

        click_button(app, find_button(app, "Wróć do danych"))
        assert_step(app, "Etap 2 z 5")
        click_button(app, app.analyze_button)
        wait_for_idle(app)

        click_button(app, app.preview_button)
        wait_for_idle(app)
        assert_step(app, "Etap 4 z 5")

        click_button(app, find_button(app, "Wróć do ustawień"))
        assert_step(app, "Etap 3 z 5")
        click_button(app, app.preview_button)
        wait_for_idle(app)

        click_button(app, find_button(app, "Cofnij zmiany"))
        assert_step(app, "Etap 3 z 5")
        click_button(app, app.preview_button)
        wait_for_idle(app)

        click_button(app, app.approve_button)
        assert_step(app, "Etap 5 z 5")
        if app.xlsx_export_options.winfo_ismapped():
            raise AssertionError("Opcje Excel są widoczne dla wyniku CSV.")

        app.output_path_var.set(str(PROJECT_DIR / "temporary_test.xlsx"))
        app.update()
        if not app.xlsx_export_options.winfo_ismapped():
            raise AssertionError("Opcje Excel nie pojawiły się dla wyniku XLSX.")
        if app.csv_export_options.winfo_ismapped():
            raise AssertionError("Opcje CSV są widoczne dla wyniku XLSX.")

        click_button(app, find_button(app, "Wróć do podglądu"))
        assert_step(app, "Etap 4 z 5")
        click_button(app, app.approve_button)

        with TemporaryDirectory() as directory:
            output = Path(directory) / "result.csv"
            app.output_path_var.set(str(output))
            with patch("csv_cleaner.ui.main_window.messagebox.showinfo"):
                click_button(app, app.save_button)
                wait_for_idle(app)
            if not output.exists():
                raise AssertionError("Przycisk zapisu nie utworzył pliku.")
            if not app.last_reports or not all(path.exists() for path in app.last_reports):
                raise AssertionError("Przycisk zapisu nie utworzył raportów.")

            opened: list[Path] = []
            app._open_path = opened.append  # type: ignore[method-assign]
            click_button(app, app.open_report_button)
            click_button(app, app.open_folder_button)
            if len(opened) != 2:
                raise AssertionError("Przyciski raportu i katalogu nie zadziałały.")

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
                raise AssertionError("Pole arkusza nie pojawiło się dla pliku XLSX.")
            if app.encoding_combo.winfo_ismapped():
                raise AssertionError("Pole kodowania jest widoczne dla pliku XLSX.")
            app.sheet_combo.set("Drugi")
            click_button(app, find_button(app, "Zastosuj ustawienia"))
            wait_for_idle(app)
            if app.loaded is None or app.loaded.sheet_name != "Drugi":
                raise AssertionError("Nie wczytano wybranego arkusza.")

        for button in app._all_buttons():
            if not str(button.cget("command")):
                raise AssertionError(
                    f"Przycisk bez przypisanej akcji: {button.cget('text')}"
                )

        app._set_busy("Test wskaźnika…", True)
        if not app.progress.winfo_ismapped():
            raise AssertionError("Wskaźnik postępu nie pojawił się podczas pracy.")
        if any(not button.instate(["disabled"]) for button in app._all_buttons()):
            raise AssertionError("Nie wszystkie przyciski zostały zablokowane.")
        app._set_busy("", False)
        if app.progress.winfo_ismapped():
            raise AssertionError("Wskaźnik postępu nie został ukryty.")
    finally:
        app.unsaved_changes = False
        app.destroy()


if __name__ == "__main__":
    run_smoke_test()
    print("Kontrola interfejsu zakończona powodzeniem.")

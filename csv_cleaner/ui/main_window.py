from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
from typing import Any, Callable

import pandas as pd

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DragDropWindow = TkinterDnD.Tk
    DRAG_DROP_AVAILABLE = True
except ImportError:
    DND_FILES = None
    DragDropWindow = tk.Tk
    DRAG_DROP_AVAILABLE = False

from csv_cleaner.core.analyzer import analyze_data
from csv_cleaner.core.cleaner import clean_data
from csv_cleaner.core.exporter import ExportError, export_data
from csv_cleaner.core.file_loader import FileLoadError, LoadedFile, load_file
from csv_cleaner.core.report_generator import build_report, save_reports
from csv_cleaner.models.analysis_result import AnalysisResult
from csv_cleaner.models.cleaning_config import CleaningConfig, DuplicateConfig
from csv_cleaner.models.operation_result import OperationResult
from csv_cleaner.utils.file_helpers import human_file_size


LOGGER = logging.getLogger(__name__)
SEPARATOR_LABELS = {
    "Przecinek": ",",
    "Średnik": ";",
    "Tabulator": "\t",
    "Kreska pionowa": "|",
}


def parse_dropped_paths(
    data: str,
    splitlist: Callable[[str], tuple[str, ...]],
) -> list[Path]:
    return [Path(item).expanduser() for item in splitlist(data) if item.strip()]


def mousewheel_units(delta: int, platform: str) -> int:
    if delta == 0:
        return 0
    if platform == "darwin":
        return -1 if delta > 0 else 1
    units = int(-delta / 120)
    return units or (-1 if delta > 0 else 1)


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = ttk.Frame(self.canvas, padding=(16, 8))
        window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.content.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda event: self.canvas.itemconfigure(window, width=event.width),
        )
        self.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.bind_all("<Button-4>", self._on_linux_scroll_up, add="+")
        self.bind_all("<Button-5>", self._on_linux_scroll_down, add="+")
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _pointer_is_inside(self, event: tk.Event[Any]) -> bool:
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget == self:
                return True
            widget = widget.master
        return False

    def _on_mousewheel(self, event: tk.Event[Any]) -> str | None:
        if not self._pointer_is_inside(event):
            return None
        units = mousewheel_units(int(event.delta), sys.platform)
        if units:
            self.canvas.yview_scroll(units, "units")
        return "break"

    def _on_linux_scroll_up(self, event: tk.Event[Any]) -> str | None:
        if not self._pointer_is_inside(event):
            return None
        self.canvas.yview_scroll(-1, "units")
        return "break"

    def _on_linux_scroll_down(self, event: tk.Event[Any]) -> str | None:
        if not self._pointer_is_inside(event):
            return None
        self.canvas.yview_scroll(1, "units")
        return "break"


class CSVTree(ttk.Frame):
    def __init__(self, parent: tk.Misc, height: int = 16) -> None:
        super().__init__(parent)
        self.tree = ttk.Treeview(self, show="headings", height=height)
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def show_frame(self, frame: pd.DataFrame, limit: int = 100) -> None:
        self.tree.delete(*self.tree.get_children())
        columns = [str(item) for item in frame.columns]
        self.tree.configure(columns=columns)
        for column in columns:
            self.tree.heading(column, text=column)
            self.tree.column(column, width=140, minwidth=80, stretch=True)
        for _, row in frame.head(limit).iterrows():
            values = ["∅" if pd.isna(value) else str(value) for value in row]
            self.tree.insert("", "end", values=values)

    def show_changes(self, changes: list[Any]) -> None:
        columns = ["Wiersz", "Kolumna", "Przed", "Po", "Operacja"]
        self.tree.delete(*self.tree.get_children())
        self.tree.configure(columns=columns)
        widths = [80, 150, 180, 180, 220]
        for column, width in zip(columns, widths):
            self.tree.heading(column, text=column)
            self.tree.column(column, width=width, minwidth=70)
        for change in changes:
            self.tree.insert(
                "",
                "end",
                values=(
                    change.row,
                    change.column,
                    change.before,
                    change.after,
                    change.operation,
                ),
            )


class MainWindow(DragDropWindow):
    def __init__(self) -> None:
        super().__init__()
        self.title("CSV Cleaner")
        self.geometry("1120x760")
        self.minsize(900, 620)
        self.loaded: LoadedFile | None = None
        self.analysis: AnalysisResult | None = None
        self.cleaning_result: OperationResult | None = None
        self.last_output: Path | None = None
        self.last_reports: tuple[Path, Path] | None = None
        self.unsaved_changes = False
        self.is_busy = False
        self._busy_button_states: dict[ttk.Button, bool] = {}
        self._task_queue: queue.Queue[
            tuple[str, Any, Callable[[Any], None] | None]
        ] = queue.Queue()
        self.step_frames: dict[str, ttk.Frame] = {}
        self.busy_var = tk.StringVar(value="")
        self._configure_style()
        self._build_shell()
        self._build_file_step()
        self._build_data_step()
        self._build_analysis_step()
        self._build_preview_step()
        self._build_export_step()
        self.show_step("file")
        self.after(25, self._poll_task_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        themes = style.theme_names()
        if sys.platform == "darwin" and "aqua" in themes:
            style.theme_use("aqua")
        elif sys.platform == "darwin" and "default" in themes:
            style.theme_use("default")
        elif sys.platform != "darwin" and "clam" in themes:
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("TkDefaultFont", 24, "bold"))
        style.configure("Heading.TLabel", font=("TkDefaultFont", 15, "bold"))
        style.configure("Muted.TLabel", foreground="#4b5563")
        style.configure("Accent.TButton", font=("TkDefaultFont", 11, "bold"), padding=(16, 10))
        style.configure("Card.TFrame", relief="solid", borderwidth=1)
        style.configure("DropActive.TFrame", relief="solid", borderwidth=2)

    def _build_shell(self) -> None:
        header = ttk.Frame(self, padding=(22, 14))
        header.pack(fill="x")
        ttk.Label(header, text="CSV Cleaner", style="Heading.TLabel").pack(side="left")
        self.step_label = ttk.Label(header, text="")
        self.step_label.pack(side="right")
        ttk.Separator(self).pack(fill="x")
        self.container = ttk.Frame(self)
        self.container.pack(fill="both", expand=True)
        self.footer = ttk.Frame(self, padding=(18, 8))
        self.footer.pack(fill="x")
        self.footer.columnconfigure(0, weight=1)
        self.busy_label = ttk.Label(
            self.footer,
            textvariable=self.busy_var,
            style="Muted.TLabel",
        )
        self.busy_label.grid(row=0, column=1, sticky="e", padx=(0, 12))
        self.progress = ttk.Progressbar(
            self.footer,
            mode="indeterminate",
            length=180,
        )
        self.progress.grid(row=0, column=2, sticky="e")
        self.progress.grid_remove()

    def _new_step(self, key: str) -> ttk.Frame:
        frame = ttk.Frame(self.container, padding=24)
        self.step_frames[key] = frame
        return frame

    def show_step(self, key: str) -> None:
        labels = {
            "file": "Etap 1 z 5  •  Wybór pliku",
            "data": "Etap 2 z 5  •  Dane",
            "analysis": "Etap 3 z 5  •  Problemy",
            "preview": "Etap 4 z 5  •  Podgląd zmian",
            "export": "Etap 5 z 5  •  Zapis",
        }
        for frame in self.step_frames.values():
            frame.pack_forget()
        self.step_frames[key].pack(fill="both", expand=True)
        self.step_label.configure(text=labels[key])

    def _build_file_step(self) -> None:
        frame = self._new_step("file")
        center = ttk.Frame(frame)
        center.place(relx=0.5, rely=0.45, anchor="center")
        ttk.Label(center, text="Uporządkuj dane przed kolejnym raportem", style="Title.TLabel").pack(pady=(0, 10))
        ttk.Label(
            center,
            text="Wybierz plik CSV lub XLSX. Analiza i czyszczenie odbywają się wyłącznie na tym komputerze.",
            style="Muted.TLabel",
            wraplength=700,
            justify="center",
        ).pack(pady=(0, 28))
        self.drop_zone = ttk.Frame(center, style="Card.TFrame", padding=38)
        self.drop_zone.pack(fill="x")
        self.drop_title = ttk.Label(
            self.drop_zone,
            text="Przeciągnij tutaj plik CSV lub XLSX",
            style="Heading.TLabel",
        )
        self.drop_title.pack(pady=(0, 10))
        self.drop_hint_var = tk.StringVar(
            value="Pliki do 100 MB. Oryginał nie zostanie zmieniony."
        )
        self.drop_hint = ttk.Label(
            self.drop_zone,
            textvariable=self.drop_hint_var,
            style="Muted.TLabel",
        )
        self.drop_hint.pack(pady=(0, 18))
        self.drop_button = ttk.Button(
            self.drop_zone,
            text="Wybierz plik",
            style="Accent.TButton",
            command=self._choose_file,
        )
        self.drop_button.pack()
        self._configure_file_drop()

    def _configure_file_drop(self) -> None:
        if not DRAG_DROP_AVAILABLE or DND_FILES is None:
            self.drop_hint_var.set(
                "Przeciąganie wymaga biblioteki tkinterdnd2. Nadal możesz wybrać plik przyciskiem."
            )
            return
        for widget in (self.drop_zone, self.drop_title, self.drop_hint):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<DropEnter>>", self._on_drop_enter)
            widget.dnd_bind("<<DropLeave>>", self._on_drop_leave)
            widget.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop_enter(self, event: Any) -> str:
        self.drop_zone.configure(style="DropActive.TFrame")
        self.drop_hint_var.set("Upuść plik, aby rozpocząć wczytywanie.")
        return str(event.action)

    def _on_drop_leave(self, event: Any) -> str:
        self._reset_drop_zone()
        return str(event.action)

    def _on_drop(self, event: Any) -> str:
        self._reset_drop_zone()
        paths = parse_dropped_paths(str(event.data), self.tk.splitlist)
        if len(paths) != 1:
            messagebox.showwarning(
                "CSV Cleaner",
                "Upuść dokładnie jeden plik CSV albo XLSX.",
                parent=self,
            )
            return str(event.action)
        self._load(str(paths[0]))
        return str(event.action)

    def _reset_drop_zone(self) -> None:
        self.drop_zone.configure(style="Card.TFrame")
        self.drop_hint_var.set("Pliki do 100 MB. Oryginał nie zostanie zmieniony.")

    def _build_data_step(self) -> None:
        frame = self._new_step("data")
        top = ttk.Frame(frame)
        top.pack(fill="x", pady=(0, 12))
        ttk.Label(top, text="Podgląd danych", style="Title.TLabel").pack(side="left")
        ttk.Button(
            top,
            text="Wybierz inny plik",
            command=self._choose_file,
        ).pack(side="right")
        self.file_info = ttk.Label(frame, text="", style="Muted.TLabel")
        self.file_info.pack(fill="x", pady=(0, 10))
        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(0, 12))
        self.encoding_label = ttk.Label(controls, text="Kodowanie")
        self.encoding_label.grid(row=0, column=0, sticky="w")
        self.encoding_var = tk.StringVar(value="utf-8")
        self.encoding_combo = ttk.Combobox(
            controls,
            textvariable=self.encoding_var,
            values=("utf-8", "utf-8-sig", "cp1250", "iso-8859-2"),
            width=14,
            state="readonly",
        )
        self.encoding_combo.grid(row=1, column=0, padx=(0, 12))
        self.separator_label = ttk.Label(controls, text="Separator")
        self.separator_label.grid(row=0, column=1, sticky="w")
        self.separator_var = tk.StringVar(value="Przecinek")
        self.separator_combo = ttk.Combobox(
            controls,
            textvariable=self.separator_var,
            values=tuple(SEPARATOR_LABELS),
            width=18,
            state="readonly",
        )
        self.separator_combo.grid(row=1, column=1, padx=(0, 12))
        self.sheet_label = ttk.Label(controls, text="Arkusz Excel")
        self.sheet_label.grid(row=0, column=2, sticky="w")
        self.sheet_var = tk.StringVar()
        self.sheet_combo = ttk.Combobox(controls, textvariable=self.sheet_var, width=24, state="readonly")
        self.sheet_combo.grid(row=1, column=2, padx=(0, 12))
        self.reload_button = ttk.Button(
            controls,
            text="Zastosuj ustawienia",
            command=self._reload_with_options,
        )
        self.reload_button.grid(row=1, column=3)
        self.data_options_hint = ttk.Label(
            controls,
            text="Po zmianie kodowania lub separatora wybierz Zastosuj ustawienia.",
            style="Muted.TLabel",
        )
        self.data_options_hint.grid(
            row=2,
            column=0,
            columnspan=4,
            sticky="w",
            pady=(5, 0),
        )
        self.data_tree = CSVTree(frame, height=18)
        self.data_tree.pack(fill="both", expand=True)
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(14, 0))
        self.analyze_button = ttk.Button(
            actions,
            text="Rozpocznij analizę",
            style="Accent.TButton",
            command=self._analyze,
        )
        self.analyze_button.pack(side="right")

    def _build_analysis_step(self) -> None:
        frame = self._new_step("analysis")
        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, text="Wykryte problemy i operacje", style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="Wróć do danych", command=lambda: self.show_step("data")).pack(side="right")
        self.analysis_summary = ttk.Label(frame, text="", style="Muted.TLabel")
        self.analysis_summary.pack(fill="x", pady=(6, 10))
        self.analysis_scroll = ScrollableFrame(frame)
        self.analysis_scroll.pack(fill="both", expand=True)
        content = self.analysis_scroll.content

        self.remove_empty_rows_var = tk.BooleanVar()
        self.remove_empty_columns_var = tk.BooleanVar()
        self.trim_var = tk.BooleanVar()
        self.collapse_var = tk.BooleanVar()
        self.duplicates_var = tk.BooleanVar()
        self.columns_var = tk.BooleanVar()
        self.dates_var = tk.BooleanVar()
        self.email_var = tk.BooleanVar()
        self.missing_var = tk.BooleanVar()

        self.issue_labels: dict[str, ttk.Label] = {}
        checks = [
            ("empty_rows", "Usuń całkowicie puste wiersze", self.remove_empty_rows_var),
            ("empty_columns", "Usuń całkowicie puste kolumny", self.remove_empty_columns_var),
            ("whitespace", "Usuń zbędne odstępy", self.trim_var),
            ("duplicates", "Obsłuż duplikaty", self.duplicates_var),
            ("missing", "Obsłuż brakujące wartości", self.missing_var),
            ("invalid_emails", "Waliduj adresy poczty", self.email_var),
        ]
        for row, (key, text, variable) in enumerate(checks):
            ttk.Checkbutton(content, text=text, variable=variable).grid(row=row, column=0, sticky="w", pady=4)
            label = ttk.Label(content, text="", style="Muted.TLabel")
            label.grid(row=row, column=1, sticky="w", padx=18)
            self.issue_labels[key] = label

        row = len(checks)
        ttk.Label(content, text="Przykładowe rekordy").grid(row=row, column=0, sticky="w", pady=(8, 2))
        self.issue_example_var = tk.StringVar()
        self.issue_example_combo = ttk.Combobox(
            content,
            textvariable=self.issue_example_var,
            state="readonly",
            width=34,
        )
        self.issue_example_combo.grid(row=row, column=1, sticky="w", padx=12, pady=(8, 2))
        self.issue_example_combo.bind("<<ComboboxSelected>>", self._show_issue_examples)
        row += 1
        self.issue_examples_text = tk.Text(content, height=5, wrap="none", state="disabled")
        self.issue_examples_text.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        row += 1
        ttk.Checkbutton(
            content,
            text="Scalaj wielokrotne odstępy wewnątrz tekstu",
            variable=self.collapse_var,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=(24, 0))
        row += 1
        ttk.Separator(content).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        ttk.Label(content, text="Duplikaty", style="Heading.TLabel").grid(row=row, column=0, sticky="w")
        row += 1
        ttk.Label(content, text="Kolumny, rozdzielone przecinkami; puste pole oznacza wszystkie").grid(row=row, column=0, sticky="w")
        self.duplicate_columns_var = tk.StringVar()
        ttk.Entry(content, textvariable=self.duplicate_columns_var, width=60).grid(row=row, column=1, sticky="ew", padx=12)
        row += 1
        ttk.Label(content, text="Sposób obsługi").grid(row=row, column=0, sticky="w")
        self.duplicate_keep_var = tk.StringVar(value="Zachowaj pierwszy")
        ttk.Combobox(
            content,
            textvariable=self.duplicate_keep_var,
            values=("Zachowaj pierwszy", "Zachowaj ostatni", "Usuń wszystkie powtórzenia", "Tylko oznacz"),
            state="readonly",
            width=28,
        ).grid(row=row, column=1, sticky="w", padx=12, pady=4)
        row += 1
        ttk.Separator(content).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        ttk.Checkbutton(
            content,
            text="Standaryzuj nazwy kolumn",
            variable=self.columns_var,
        ).grid(row=row, column=0, sticky="w")
        self.column_case_var = tk.StringVar(value="małe litery")
        ttk.Combobox(
            content,
            textvariable=self.column_case_var,
            values=("małe litery", "WIELKIE LITERY"),
            state="readonly",
            width=20,
        ).grid(row=row, column=1, sticky="w", padx=12)
        row += 1
        self.polish_var = tk.BooleanVar()
        ttk.Checkbutton(
            content,
            text="Usuń polskie znaki z nazw kolumn",
            variable=self.polish_var,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=(24, 0))
        row += 1

        ttk.Label(content, text="Kolumny tekstowe do zmiany wielkości liter").grid(row=row, column=0, sticky="w")
        self.text_columns_var = tk.StringVar()
        ttk.Entry(content, textvariable=self.text_columns_var, width=60).grid(row=row, column=1, sticky="ew", padx=12)
        row += 1
        ttk.Label(content, text="Wielkość liter").grid(row=row, column=0, sticky="w")
        self.text_case_var = tk.StringVar(value="Bez zmian")
        ttk.Combobox(
            content,
            textvariable=self.text_case_var,
            values=("Bez zmian", "małe litery", "WIELKIE LITERY", "Pierwsza litera", "Każde Słowo"),
            state="readonly",
            width=20,
        ).grid(row=row, column=1, sticky="w", padx=12)
        row += 1
        ttk.Separator(content).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        ttk.Checkbutton(content, text="Standaryzuj daty", variable=self.dates_var).grid(row=row, column=0, sticky="w")
        self.date_columns_var = tk.StringVar()
        ttk.Entry(content, textvariable=self.date_columns_var, width=60).grid(row=row, column=1, sticky="ew", padx=12)
        row += 1
        ttk.Label(content, text="Format daty").grid(row=row, column=0, sticky="w")
        self.date_format_var = tk.StringVar(value="%Y.%m.%d")
        ttk.Combobox(
            content,
            textvariable=self.date_format_var,
            values=("%Y.%m.%d", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y.%m.%d %H:%M"),
            width=22,
        ).grid(row=row, column=1, sticky="w", padx=12)
        row += 1
        ttk.Label(content, text="Kolumny dat i tekstu podawaj po przecinku.", style="Muted.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        ttk.Separator(content).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        ttk.Label(content, text="Kolumny z adresami poczty").grid(row=row, column=0, sticky="w")
        self.email_columns_var = tk.StringVar()
        ttk.Entry(content, textvariable=self.email_columns_var, width=60).grid(row=row, column=1, sticky="ew", padx=12)
        row += 1
        ttk.Label(content, text="Nieprawidłowe adresy").grid(row=row, column=0, sticky="w")
        self.email_action_var = tk.StringVar(value="Pozostaw i raportuj")
        ttk.Combobox(
            content,
            textvariable=self.email_action_var,
            values=("Pozostaw i raportuj", "Zastąp pustą wartością"),
            state="readonly",
            width=28,
        ).grid(row=row, column=1, sticky="w", padx=12)
        row += 1
        ttk.Separator(content).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        ttk.Label(content, text="Kolumny z brakami").grid(row=row, column=0, sticky="w")
        self.missing_columns_var = tk.StringVar()
        ttk.Entry(content, textvariable=self.missing_columns_var, width=60).grid(row=row, column=1, sticky="ew", padx=12)
        row += 1
        ttk.Label(content, text="Sposób uzupełnienia").grid(row=row, column=0, sticky="w")
        self.missing_strategy_var = tk.StringVar(value="Pozostaw bez zmian")
        ttk.Combobox(
            content,
            textvariable=self.missing_strategy_var,
            values=(
                "Pozostaw bez zmian",
                "Wybrany tekst",
                "Zero",
                "Średnia",
                "Mediana",
                "Najczęstsza wartość",
                "Usuń wiersze",
            ),
            state="readonly",
            width=28,
        ).grid(row=row, column=1, sticky="w", padx=12)
        row += 1
        ttk.Label(content, text="Tekst zastępczy").grid(row=row, column=0, sticky="w")
        self.missing_replacement_var = tk.StringVar(value="brak")
        ttk.Entry(content, textvariable=self.missing_replacement_var, width=30).grid(row=row, column=1, sticky="w", padx=12)
        content.columnconfigure(1, weight=1)

        self.preview_button = ttk.Button(
            frame,
            text="Przygotuj podgląd zmian",
            style="Accent.TButton",
            command=self._preview_changes,
        )
        self.preview_button.pack(side="right", pady=(12, 0))

    def _build_preview_step(self) -> None:
        frame = self._new_step("preview")
        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, text="Podgląd planowanych zmian", style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="Wróć do ustawień", command=lambda: self.show_step("analysis")).pack(side="right")
        self.preview_summary = ttk.Label(frame, text="", style="Muted.TLabel")
        self.preview_summary.pack(fill="x", pady=(6, 12))
        self.change_tree = CSVTree(frame, height=18)
        self.change_tree.pack(fill="both", expand=True)
        self.warning_text = tk.Text(frame, height=4, wrap="word", state="disabled")
        self.warning_text.pack(fill="x", pady=(12, 0))
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Cofnij zmiany", command=self._reset_changes).pack(side="left")
        self.approve_button = ttk.Button(
            actions,
            text="Zatwierdź i przejdź do zapisu",
            style="Accent.TButton",
            command=self._approve_changes,
        )
        self.approve_button.pack(side="right")

    def _build_export_step(self) -> None:
        frame = self._new_step("export")
        ttk.Label(frame, text="Zapis poprawionej kopii", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Oryginalny plik pozostanie bez zmian. Raport TXT i JSON zostanie zapisany obok wyniku.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(6, 20))
        self.export_form = ttk.Frame(frame, padding=20, style="Card.TFrame")
        self.export_form.pack(fill="x")
        ttk.Label(self.export_form, text="Plik wynikowy").grid(row=0, column=0, sticky="w")
        self.output_path_var = tk.StringVar()
        self.output_path_var.trace_add("write", self._on_output_path_changed)
        ttk.Entry(
            self.export_form,
            textvariable=self.output_path_var,
        ).grid(row=1, column=0, sticky="ew", padx=(0, 10))
        ttk.Button(
            self.export_form,
            text="Wybierz",
            command=self._choose_output,
        ).grid(row=1, column=1)

        self.csv_export_options = ttk.LabelFrame(
            self.export_form,
            text="Ustawienia CSV",
            padding=(12, 8),
        )
        self.csv_export_options.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(14, 0),
        )
        ttk.Label(
            self.csv_export_options,
            text="Separator",
        ).grid(row=0, column=0, sticky="w")
        self.export_separator_var = tk.StringVar(value="Średnik")
        ttk.Combobox(
            self.csv_export_options,
            textvariable=self.export_separator_var,
            values=tuple(SEPARATOR_LABELS),
            state="readonly",
            width=20,
        ).grid(row=1, column=0, sticky="w", padx=(0, 18))
        ttk.Label(
            self.csv_export_options,
            text="Kodowanie",
        ).grid(row=0, column=1, sticky="w")
        self.export_encoding_var = tk.StringVar(value="utf-8-sig")
        ttk.Combobox(
            self.csv_export_options,
            textvariable=self.export_encoding_var,
            values=("utf-8", "utf-8-sig", "cp1250", "iso-8859-2"),
            state="readonly",
            width=20,
        ).grid(row=1, column=1, sticky="w")
        self.include_index_var = tk.BooleanVar()
        ttk.Checkbutton(
            self.csv_export_options,
            text="Zapisz indeks",
            variable=self.include_index_var,
        ).grid(
            row=2,
            column=0,
            sticky="w",
            pady=(14, 0),
        )
        ttk.Label(
            self.csv_export_options,
            text="Wartość pusta",
        ).grid(row=2, column=1, sticky="w", pady=(14, 0))
        self.empty_value_var = tk.StringVar()
        ttk.Entry(
            self.csv_export_options,
            textvariable=self.empty_value_var,
            width=24,
        ).grid(row=3, column=1, sticky="w")

        self.xlsx_export_options = ttk.LabelFrame(
            self.export_form,
            text="Ustawienia Excel",
            padding=(12, 8),
        )
        self.xlsx_export_options.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(14, 0),
        )
        ttk.Label(
            self.xlsx_export_options,
            text="Nazwa arkusza",
        ).grid(row=0, column=0, sticky="w")
        self.output_sheet_var = tk.StringVar(value="Cleaned Data")
        ttk.Entry(
            self.xlsx_export_options,
            textvariable=self.output_sheet_var,
            width=30,
        ).grid(row=1, column=0, sticky="w")
        self.export_form.columnconfigure(0, weight=1)
        self._update_export_options()
        self.export_status = ttk.Label(frame, text="", style="Muted.TLabel")
        self.export_status.pack(anchor="w", pady=16)
        actions = ttk.Frame(frame)
        actions.pack(fill="x")
        ttk.Button(actions, text="Wróć do podglądu", command=lambda: self.show_step("preview")).pack(side="left")
        self.open_folder_button = ttk.Button(actions, text="Otwórz katalog", command=self._open_output_folder, state="disabled")
        self.open_folder_button.pack(side="right", padx=(8, 0))
        self.open_report_button = ttk.Button(actions, text="Wyświetl raport", command=self._open_report, state="disabled")
        self.open_report_button.pack(side="right", padx=(8, 0))
        self.save_button = ttk.Button(
            actions,
            text="Zapisz plik",
            style="Accent.TButton",
            command=self._save,
        )
        self.save_button.pack(side="right")

    def _set_busy(self, message: str, busy: bool) -> None:
        self.busy_var.set(message if busy else "")
        if busy:
            self.progress.grid()
            self.progress.start(10)
            self._busy_button_states = {}
            for button in self._all_buttons():
                was_disabled = button.instate(["disabled"])
                self._busy_button_states[button] = was_disabled
                button.state(["disabled"])
            try:
                self.configure(cursor="watch")
            except tk.TclError:
                pass
        else:
            self.progress.stop()
            self.progress.grid_remove()
            for button, was_disabled in self._busy_button_states.items():
                if button.winfo_exists() and not was_disabled:
                    button.state(["!disabled"])
            self._busy_button_states.clear()
            try:
                self.configure(cursor="")
            except tk.TclError:
                pass
        self.update_idletasks()

    def _all_buttons(self) -> list[ttk.Button]:
        buttons: list[ttk.Button] = []
        pending: list[tk.Misc] = [self]
        while pending:
            parent = pending.pop()
            for child in parent.winfo_children():
                pending.append(child)
                if isinstance(child, ttk.Button):
                    buttons.append(child)
        return buttons

    def _run_task(
        self,
        message: str,
        function: Callable[[], Any],
        on_success: Callable[[Any], None],
    ) -> None:
        if self.is_busy:
            return
        self.is_busy = True
        self._set_busy(message, True)

        def worker() -> None:
            try:
                value = function()
            except Exception as exc:
                LOGGER.exception("Background operation failed")
                self._task_queue.put(("error", exc, None))
            else:
                self._task_queue.put(("success", value, on_success))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_task_queue(self) -> None:
        try:
            while True:
                status, value, callback = self._task_queue.get_nowait()
                if status == "error":
                    self._task_failed(value)
                elif callback is not None:
                    self._task_succeeded(value, callback)
        except queue.Empty:
            pass
        try:
            self.after(25, self._poll_task_queue)
        except tk.TclError:
            return

    def _task_failed(self, error: Exception) -> None:
        self.is_busy = False
        self._set_busy("", False)
        if isinstance(error, (FileLoadError, ExportError, ValueError)):
            message = str(error)
        elif isinstance(error, MemoryError):
            message = "Brak pamięci do wykonania operacji. Spróbuj użyć mniejszego pliku."
        else:
            message = "Wystąpił nieoczekiwany błąd. Szczegóły zapisano w lokalnym dzienniku."
        messagebox.showerror("CSV Cleaner", message, parent=self)

    def _task_succeeded(self, value: Any, callback: Callable[[Any], None]) -> None:
        try:
            callback(value)
        finally:
            self.is_busy = False
            self._set_busy("", False)

    def _choose_file(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            title="Wybierz plik danych",
            filetypes=(("Pliki danych", "*.csv *.xlsx"), ("CSV", "*.csv"), ("Excel", "*.xlsx")),
        )
        if selected:
            self._load(selected)

    def _load(self, path: str, **options: Any) -> None:
        self._run_task(
            "Wczytywanie pliku…",
            lambda: load_file(path, **options),
            self._on_loaded,
        )

    def _on_loaded(self, loaded: LoadedFile) -> None:
        self.loaded = loaded
        self.analysis = None
        self.cleaning_result = None
        self.unsaved_changes = False
        if loaded.encoding:
            self.encoding_var.set(loaded.encoding)
        if loaded.separator:
            label = next((name for name, value in SEPARATOR_LABELS.items() if value == loaded.separator), "Przecinek")
            self.separator_var.set(label)
        if loaded.sheets:
            self.sheet_combo.configure(values=loaded.sheets, state="readonly")
            self.sheet_var.set(loaded.sheet_name or loaded.sheets[0])
            self.encoding_label.grid_remove()
            self.encoding_combo.grid_remove()
            self.separator_label.grid_remove()
            self.separator_combo.grid_remove()
            self.sheet_label.grid()
            self.sheet_combo.grid()
            self.reload_button.grid_configure(column=3)
            self.data_options_hint.configure(
                text="Wybierz arkusz i zastosuj ustawienia, aby wczytać jego dane."
            )
        else:
            self.encoding_label.grid()
            self.encoding_combo.grid()
            self.separator_label.grid()
            self.separator_combo.grid()
            self.sheet_label.grid_remove()
            self.sheet_combo.grid_remove()
            self.sheet_combo.configure(values=())
            self.sheet_var.set("")
            self.reload_button.grid_configure(column=3)
            self.data_options_hint.configure(
                text="Po zmianie kodowania lub separatora wybierz Zastosuj ustawienia."
            )
        size = human_file_size(loaded.path.stat().st_size)
        self.file_info.configure(
            text=(
                f"{loaded.path.name}  •  {size}  •  "
                f"{len(loaded.data):,} wierszy  •  {len(loaded.data.columns)} kolumn"
            )
        )
        self.data_tree.show_frame(loaded.data)
        self.show_step("data")

    def _reload_with_options(self) -> None:
        if not self.loaded:
            return
        if self.loaded.path.suffix.lower() == ".csv":
            self._load(
                str(self.loaded.path),
                encoding=self.encoding_var.get(),
                separator=SEPARATOR_LABELS[self.separator_var.get()],
            )
        else:
            self._load(str(self.loaded.path), sheet_name=self.sheet_var.get())

    def _analyze(self) -> None:
        if not self.loaded:
            return
        self._run_task("Analizowanie danych…", lambda: analyze_data(self.loaded.data), self._on_analyzed)

    def _on_analyzed(self, analysis: AnalysisResult) -> None:
        self.analysis = analysis
        total = sum(item.count for item in analysis.issues)
        self.analysis_summary.configure(
            text=f"Przeanalizowano {analysis.rows:,} wierszy i {analysis.columns} kolumn. Łączna liczba wskazań: {total:,}."
        )
        variables = {
            "empty_rows": self.remove_empty_rows_var,
            "empty_columns": self.remove_empty_columns_var,
            "whitespace": self.trim_var,
            "duplicates": self.duplicates_var,
            "missing": self.missing_var,
            "invalid_emails": self.email_var,
        }
        for issue in analysis.issues:
            self.issue_labels[issue.key].configure(
                text=f"{issue.count:,}  •  {', '.join(issue.columns[:5]) or 'cały zbiór'}"
            )
            variables[issue.key].set(issue.count > 0)
        self.date_columns_var.set(", ".join(analysis.date_columns))
        self.dates_var.set(bool(analysis.date_columns))
        self.email_columns_var.set(", ".join(analysis.email_columns))
        self.missing_columns_var.set(", ".join(analysis.missing_by_column))
        issue_names = [issue.name for issue in analysis.issues if issue.count > 0]
        self.issue_example_combo.configure(values=issue_names)
        self.issue_example_var.set(issue_names[0] if issue_names else "")
        self._show_issue_examples()
        self.show_step("analysis")

    def _show_issue_examples(self, _event: tk.Event[Any] | None = None) -> None:
        if not self.analysis:
            return
        selected = self.issue_example_var.get()
        issue = next((item for item in self.analysis.issues if item.name == selected), None)
        lines: list[str] = []
        if issue:
            if issue.examples:
                for example in issue.examples:
                    row = example.get("row", "")
                    values = ", ".join(
                        f"{key}={value}" for key, value in example.items() if key != "row"
                    )
                    lines.append(f"Wiersz {row}: {values}")
            elif issue.columns:
                lines.append("Kolumny: " + ", ".join(issue.columns))
        if not lines:
            lines.append("Brak przykładowych rekordów dla tego problemu.")
        self.issue_examples_text.configure(state="normal")
        self.issue_examples_text.delete("1.0", "end")
        self.issue_examples_text.insert("1.0", "\n".join(lines))
        self.issue_examples_text.configure(state="disabled")

    @staticmethod
    def _columns_from(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def _build_config(self) -> CleaningConfig:
        duplicate_keep = {
            "Zachowaj pierwszy": "first",
            "Zachowaj ostatni": "last",
            "Usuń wszystkie powtórzenia": "remove_all",
            "Tylko oznacz": "mark",
        }[self.duplicate_keep_var.get()]
        case_mode = {
            "Bez zmian": "none",
            "małe litery": "lower",
            "WIELKIE LITERY": "upper",
            "Pierwsza litera": "capitalize",
            "Każde Słowo": "title",
        }[self.text_case_var.get()]
        missing_strategy = {
            "Pozostaw bez zmian": "keep",
            "Wybrany tekst": "text",
            "Zero": "zero",
            "Średnia": "mean",
            "Mediana": "median",
            "Najczęstsza wartość": "mode",
            "Usuń wiersze": "drop",
        }[self.missing_strategy_var.get()]
        return CleaningConfig(
            remove_empty_rows=self.remove_empty_rows_var.get(),
            remove_empty_columns=self.remove_empty_columns_var.get(),
            trim_whitespace=self.trim_var.get(),
            collapse_internal_spaces=self.collapse_var.get(),
            duplicates=DuplicateConfig(
                enabled=self.duplicates_var.get(),
                columns=self._columns_from(self.duplicate_columns_var.get()),
                keep=duplicate_keep,
            ),
            standardize_column_names=self.columns_var.get(),
            column_case="lower" if self.column_case_var.get() == "małe litery" else "upper",
            remove_polish_characters=self.polish_var.get(),
            text_case_columns=self._columns_from(self.text_columns_var.get()),
            text_case_mode=case_mode,
            date_columns=self._columns_from(self.date_columns_var.get()) if self.dates_var.get() else [],
            date_output_format=self.date_format_var.get(),
            email_columns=self._columns_from(self.email_columns_var.get()) if self.email_var.get() else [],
            invalid_email_action="empty" if self.email_action_var.get() == "Zastąp pustą wartością" else "keep",
            missing_strategy=missing_strategy if self.missing_var.get() else "keep",
            missing_replacement=self.missing_replacement_var.get(),
            missing_columns=self._columns_from(self.missing_columns_var.get()),
        )

    def _preview_changes(self) -> None:
        if not self.loaded:
            return
        config = self._build_config()
        self._run_task(
            "Przygotowywanie podglądu…",
            lambda: clean_data(self.loaded.data, config),
            self._on_preview_ready,
        )

    def _on_preview_ready(self, result: OperationResult) -> None:
        self.cleaning_result = result
        self.unsaved_changes = True
        shown = len(result.changes)
        self.preview_summary.configure(
            text=(
                f"Zmiany: {result.total_changes:,}, pokazano: {shown:,}. "
                f"Usunięte wiersze: {result.removed_rows:,}, kolumny: {result.removed_columns:,}."
            )
        )
        self.change_tree.show_changes(result.changes)
        self.warning_text.configure(state="normal")
        self.warning_text.delete("1.0", "end")
        self.warning_text.insert(
            "1.0",
            "\n".join(result.warnings[:20]) if result.warnings else "Brak ostrzeżeń.",
        )
        self.warning_text.configure(state="disabled")
        self.show_step("preview")

    def _reset_changes(self) -> None:
        self.cleaning_result = None
        self.unsaved_changes = False
        self.show_step("analysis")

    def _approve_changes(self) -> None:
        if not self.cleaning_result or not self.loaded:
            return
        suffix = self.loaded.path.suffix.lower()
        self.output_path_var.set(str(self.loaded.path.with_name(f"{self.loaded.path.stem}_cleaned{suffix}")))
        self.show_step("export")

    def _on_output_path_changed(self, *_args: str) -> None:
        self._update_export_options()

    def _update_export_options(self) -> None:
        if not hasattr(self, "csv_export_options"):
            return
        suffix = Path(self.output_path_var.get().strip()).suffix.lower()
        if suffix == ".xlsx":
            self.csv_export_options.grid_remove()
            self.xlsx_export_options.grid()
        else:
            self.xlsx_export_options.grid_remove()
            self.csv_export_options.grid()

    def _choose_output(self) -> None:
        initial = Path(self.output_path_var.get()) if self.output_path_var.get() else Path.cwd() / "data_cleaned.csv"
        selected = filedialog.asksaveasfilename(
            parent=self,
            title="Zapisz poprawioną kopię",
            initialdir=initial.parent,
            initialfile=initial.name,
            defaultextension=initial.suffix or ".csv",
            filetypes=(("CSV", "*.csv"), ("Excel", "*.xlsx")),
        )
        if selected:
            self.output_path_var.set(selected)

    def _save(self) -> None:
        if not self.loaded or not self.cleaning_result:
            return
        value = self.output_path_var.get().strip()
        if not value:
            messagebox.showwarning("CSV Cleaner", "Wybierz plik wynikowy.", parent=self)
            return
        target = Path(value).expanduser().resolve()
        overwrite = False
        if target == self.loaded.path:
            confirmed = messagebox.askyesno(
                "Potwierdź nadpisanie",
                "Wybrano plik źródłowy. Czy na pewno chcesz go nadpisać?",
                parent=self,
                default=messagebox.NO,
            )
            if not confirmed:
                return
            overwrite = True
        elif target.exists():
            overwrite = messagebox.askyesno(
                "Plik już istnieje",
                "Czy zastąpić istniejący plik?",
                parent=self,
                default=messagebox.NO,
            )
            if not overwrite:
                return

        result_to_save = self.cleaning_result
        source_path = self.loaded.path
        rows_before = len(self.loaded.data)
        columns_before = len(self.loaded.data.columns)
        export_separator = SEPARATOR_LABELS[self.export_separator_var.get()]
        export_encoding = self.export_encoding_var.get()
        include_index = self.include_index_var.get()
        empty_value = self.empty_value_var.get()
        output_sheet = self.output_sheet_var.get()

        def save_all() -> tuple[Path, tuple[Path, Path]]:
            output = export_data(
                result_to_save.data,
                target,
                separator=export_separator,
                encoding=export_encoding,
                include_index=include_index,
                empty_value=empty_value,
                sheet_name=output_sheet,
                overwrite=overwrite,
            )
            report = build_report(
                source_path,
                output,
                rows_before,
                columns_before,
                result_to_save,
            )
            return output, save_reports(report, output)

        self._run_task("Zapisywanie wyniku i raportów…", save_all, self._on_saved)

    def _on_saved(self, value: tuple[Path, tuple[Path, Path]]) -> None:
        self.last_output, self.last_reports = value
        self.unsaved_changes = False
        self.export_status.configure(
            text=f"Gotowe. Zapisano {self.last_output.name} oraz dwa raporty."
        )
        self.open_folder_button.configure(state="normal")
        self.open_report_button.configure(state="normal")
        messagebox.showinfo("CSV Cleaner", "Plik i raporty zostały zapisane.", parent=self)

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError:
            messagebox.showerror("CSV Cleaner", f"Nie można otworzyć: {path}", parent=self)

    def _open_output_folder(self) -> None:
        if self.last_output:
            self._open_path(self.last_output.parent)

    def _open_report(self) -> None:
        if self.last_reports:
            self._open_path(self.last_reports[0])

    def _on_close(self) -> None:
        if self.unsaved_changes:
            confirmed = messagebox.askyesno(
                "Niezapisane zmiany",
                "Masz niezapisany podgląd zmian. Czy zamknąć aplikację?",
                parent=self,
                default=messagebox.NO,
            )
            if not confirmed:
                return
        self.destroy()

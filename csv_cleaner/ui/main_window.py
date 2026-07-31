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
from csv_cleaner.i18n import (
    DEFAULT_LANGUAGE,
    LocalizedError,
    LocalizedMessage,
    LocalizedValueError,
    translate,
)
from csv_cleaner.models.analysis_result import AnalysisResult
from csv_cleaner.models.cleaning_config import CleaningConfig, DuplicateConfig
from csv_cleaner.models.operation_result import OperationResult
from csv_cleaner.utils.file_helpers import human_file_size


LOGGER = logging.getLogger(__name__)
SEPARATORS = {
    "comma": ",",
    "semicolon": ";",
    "tab": "\t",
    "pipe": "|",
}
CHOICE_GROUPS = {
    "separator": (
        ("comma", "separator.comma"),
        ("semicolon", "separator.semicolon"),
        ("tab", "separator.tab"),
        ("pipe", "separator.pipe"),
    ),
    "duplicate_keep": (
        ("first", "choice.keep_first"),
        ("last", "choice.keep_last"),
        ("remove_all", "choice.remove_all_duplicates"),
        ("mark", "choice.mark_only"),
    ),
    "column_case": (
        ("lower", "choice.lowercase"),
        ("upper", "choice.uppercase"),
    ),
    "text_case": (
        ("none", "choice.no_change"),
        ("lower", "choice.lowercase"),
        ("upper", "choice.uppercase"),
        ("capitalize", "choice.capitalize"),
        ("title", "choice.title_case"),
    ),
    "email_action": (
        ("keep", "choice.keep_report"),
        ("empty", "choice.replace_empty"),
    ),
    "missing_strategy": (
        ("keep", "choice.keep_missing"),
        ("text", "choice.custom_text"),
        ("zero", "choice.zero"),
        ("mean", "choice.mean"),
        ("median", "choice.median"),
        ("mode", "choice.mode"),
        ("drop", "choice.drop_rows"),
    ),
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

    def show_changes(
        self,
        changes: list[Any],
        translator: Callable[[str], str],
    ) -> None:
        columns = [
            translator("change.row"),
            translator("change.column"),
            translator("change.before"),
            translator("change.after"),
            translator("change.operation"),
        ]
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
                    translator(change.row_key) if change.row_key else change.row,
                    change.column,
                    translator(change.before_key) if change.before_key else change.before,
                    translator(change.after_key) if change.after_key else change.after,
                    translator(change.operation),
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
        self.language = DEFAULT_LANGUAGE
        self.language_var = tk.StringVar(value=self.language)
        self.current_step = "file"
        self._translated_widgets: list[tuple[tk.Misc, str]] = []
        self._choice_widgets: list[
            tuple[ttk.Combobox, tk.StringVar, str]
        ] = []
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

    def _t(self, key: str, **values: Any) -> str:
        return translate(self.language, key, **values)

    def _label(self, parent: tk.Misc, key: str, **options: Any) -> ttk.Label:
        widget = ttk.Label(parent, text=self._t(key), **options)
        self._translated_widgets.append((widget, key))
        return widget

    def _button(self, parent: tk.Misc, key: str, **options: Any) -> ttk.Button:
        widget = ttk.Button(parent, text=self._t(key), **options)
        self._translated_widgets.append((widget, key))
        return widget

    def _checkbutton(
        self,
        parent: tk.Misc,
        key: str,
        **options: Any,
    ) -> ttk.Checkbutton:
        widget = ttk.Checkbutton(parent, text=self._t(key), **options)
        self._translated_widgets.append((widget, key))
        return widget

    def _label_frame(
        self,
        parent: tk.Misc,
        key: str,
        **options: Any,
    ) -> ttk.LabelFrame:
        widget = ttk.LabelFrame(parent, text=self._t(key), **options)
        self._translated_widgets.append((widget, key))
        return widget

    def _choice_values(self, group: str) -> tuple[str, ...]:
        return tuple(self._t(key) for _, key in CHOICE_GROUPS[group])

    def _choice_label(self, group: str, code: str) -> str:
        key = next(
            key
            for candidate, key in CHOICE_GROUPS[group]
            if candidate == code
        )
        return self._t(key)

    @staticmethod
    def _choice_code_for_language(
        group: str,
        value: str,
        language: str,
    ) -> str:
        for code, key in CHOICE_GROUPS[group]:
            if translate(language, key) == value:
                return code
        return CHOICE_GROUPS[group][0][0]

    def _choice_code(self, group: str, value: str) -> str:
        return self._choice_code_for_language(group, value, self.language)

    def _choice_combo(
        self,
        parent: tk.Misc,
        variable: tk.StringVar,
        group: str,
        default: str,
        **options: Any,
    ) -> ttk.Combobox:
        variable.set(self._choice_label(group, default))
        widget = ttk.Combobox(
            parent,
            textvariable=variable,
            values=self._choice_values(group),
            **options,
        )
        self._choice_widgets.append((widget, variable, group))
        return widget

    def _change_language(self) -> None:
        selected = self.language_var.get()
        if selected == self.language or selected not in {"en", "pl"}:
            return
        previous = self.language
        replacement_uses_default = self.missing_replacement_var.get() in {
            translate(language, "choice.missing_text")
            for language in ("en", "pl")
        }
        sheet_uses_default = self.output_sheet_var.get() in {
            translate(language, "choice.cleaned_sheet")
            for language in ("en", "pl")
        }
        choice_codes = [
            self._choice_code_for_language(group, variable.get(), previous)
            for _, variable, group in self._choice_widgets
        ]
        self.language = selected
        for widget, key in self._translated_widgets:
            if widget.winfo_exists():
                widget.configure(text=self._t(key))
        for (widget, variable, group), code in zip(
            self._choice_widgets,
            choice_codes,
        ):
            if widget.winfo_exists():
                widget.configure(values=self._choice_values(group))
                variable.set(self._choice_label(group, code))
        if replacement_uses_default:
            self.missing_replacement_var.set(self._t("choice.missing_text"))
        if sheet_uses_default:
            self.output_sheet_var.set(self._t("choice.cleaned_sheet"))
        self.show_step(self.current_step)
        self._refresh_dynamic_text()

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
        language_switch = ttk.Frame(header)
        language_switch.pack(side="right", padx=(22, 0))
        self._label(language_switch, "language").pack(side="left", padx=(0, 6))
        ttk.Radiobutton(
            language_switch,
            text="EN",
            value="en",
            variable=self.language_var,
            command=self._change_language,
        ).pack(side="left")
        ttk.Radiobutton(
            language_switch,
            text="PL",
            value="pl",
            variable=self.language_var,
            command=self._change_language,
        ).pack(side="left")
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
        for frame in self.step_frames.values():
            frame.pack_forget()
        self.step_frames[key].pack(fill="both", expand=True)
        self.current_step = key
        self.step_label.configure(text=self._t(f"step.{key}"))

    def _build_file_step(self) -> None:
        frame = self._new_step("file")
        center = ttk.Frame(frame)
        center.place(relx=0.5, rely=0.45, anchor="center")
        self._label(center, "file.title", style="Title.TLabel").pack(
            pady=(0, 10)
        )
        self._label(
            center,
            "file.description",
            style="Muted.TLabel",
            wraplength=700,
            justify="center",
        ).pack(pady=(0, 28))
        self.drop_zone = ttk.Frame(center, style="Card.TFrame", padding=38)
        self.drop_zone.pack(fill="x")
        self.drop_title = self._label(
            self.drop_zone,
            "file.drop_title",
            style="Heading.TLabel",
        )
        self.drop_title.pack(pady=(0, 10))
        self.drop_hint_var = tk.StringVar(value=self._t("file.drop_hint"))
        self.drop_hint = ttk.Label(
            self.drop_zone,
            textvariable=self.drop_hint_var,
            style="Muted.TLabel",
        )
        self.drop_hint.pack(pady=(0, 18))
        self.drop_button = self._button(
            self.drop_zone,
            "file.choose",
            style="Accent.TButton",
            command=self._choose_file,
        )
        self.drop_button.pack()
        self._configure_file_drop()

    def _configure_file_drop(self) -> None:
        if not DRAG_DROP_AVAILABLE or DND_FILES is None:
            self.drop_hint_var.set(self._t("file.drop_unavailable"))
            return
        for widget in (self.drop_zone, self.drop_title, self.drop_hint):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<DropEnter>>", self._on_drop_enter)
            widget.dnd_bind("<<DropLeave>>", self._on_drop_leave)
            widget.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop_enter(self, event: Any) -> str:
        self.drop_zone.configure(style="DropActive.TFrame")
        self.drop_hint_var.set(self._t("file.drop_active"))
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
                self._t("file.drop_single"),
                parent=self,
            )
            return str(event.action)
        self._load(str(paths[0]))
        return str(event.action)

    def _reset_drop_zone(self) -> None:
        self.drop_zone.configure(style="Card.TFrame")
        self.drop_hint_var.set(self._t("file.drop_hint"))

    def _build_data_step(self) -> None:
        frame = self._new_step("data")
        top = ttk.Frame(frame)
        top.pack(fill="x", pady=(0, 12))
        self._label(top, "data.title", style="Title.TLabel").pack(side="left")
        self._button(
            top,
            "data.choose_another",
            command=self._choose_file,
        ).pack(side="right")
        self.file_info = ttk.Label(frame, text="", style="Muted.TLabel")
        self.file_info.pack(fill="x", pady=(0, 10))
        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(0, 12))
        self.encoding_label = self._label(controls, "data.encoding")
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
        self.separator_label = self._label(controls, "data.separator")
        self.separator_label.grid(row=0, column=1, sticky="w")
        self.separator_var = tk.StringVar()
        self.separator_combo = self._choice_combo(
            controls,
            self.separator_var,
            "separator",
            "comma",
            width=18,
            state="readonly",
        )
        self.separator_combo.grid(row=1, column=1, padx=(0, 12))
        self.sheet_label = self._label(controls, "data.sheet")
        self.sheet_label.grid(row=0, column=2, sticky="w")
        self.sheet_var = tk.StringVar()
        self.sheet_combo = ttk.Combobox(controls, textvariable=self.sheet_var, width=24, state="readonly")
        self.sheet_combo.grid(row=1, column=2, padx=(0, 12))
        self.reload_button = self._button(
            controls,
            "data.apply",
            command=self._reload_with_options,
        )
        self.reload_button.grid(row=1, column=3)
        self.data_options_hint = ttk.Label(
            controls,
            text=self._t("data.csv_hint"),
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
        self.analyze_button = self._button(
            actions,
            "data.start_analysis",
            style="Accent.TButton",
            command=self._analyze,
        )
        self.analyze_button.pack(side="right")

    def _build_analysis_step(self) -> None:
        frame = self._new_step("analysis")
        top = ttk.Frame(frame)
        top.pack(fill="x")
        self._label(top, "analysis.title", style="Title.TLabel").pack(side="left")
        self._button(
            top,
            "analysis.back",
            command=lambda: self.show_step("data"),
        ).pack(side="right")
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
            ("empty_rows", "analysis.remove_empty_rows", self.remove_empty_rows_var),
            ("empty_columns", "analysis.remove_empty_columns", self.remove_empty_columns_var),
            ("whitespace", "analysis.trim", self.trim_var),
            ("duplicates", "analysis.duplicates", self.duplicates_var),
            ("missing", "analysis.missing", self.missing_var),
            ("invalid_emails", "analysis.email", self.email_var),
        ]
        for row, (key, text_key, variable) in enumerate(checks):
            self._checkbutton(content, text_key, variable=variable).grid(
                row=row,
                column=0,
                sticky="w",
                pady=4,
            )
            label = ttk.Label(content, text="", style="Muted.TLabel")
            label.grid(row=row, column=1, sticky="w", padx=18)
            self.issue_labels[key] = label

        row = len(checks)
        self._label(content, "analysis.examples").grid(
            row=row,
            column=0,
            sticky="w",
            pady=(8, 2),
        )
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
        self._checkbutton(
            content,
            "analysis.collapse_spaces",
            variable=self.collapse_var,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=(24, 0))
        row += 1
        ttk.Separator(content).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        self._label(
            content,
            "analysis.duplicates_heading",
            style="Heading.TLabel",
        ).grid(row=row, column=0, sticky="w")
        row += 1
        self._label(content, "analysis.duplicate_columns").grid(
            row=row,
            column=0,
            sticky="w",
        )
        self.duplicate_columns_var = tk.StringVar()
        ttk.Entry(content, textvariable=self.duplicate_columns_var, width=60).grid(row=row, column=1, sticky="ew", padx=12)
        row += 1
        self._label(content, "analysis.handling").grid(
            row=row,
            column=0,
            sticky="w",
        )
        self.duplicate_keep_var = tk.StringVar()
        self._choice_combo(
            content,
            self.duplicate_keep_var,
            "duplicate_keep",
            "first",
            state="readonly",
            width=28,
        ).grid(row=row, column=1, sticky="w", padx=12, pady=4)
        row += 1
        ttk.Separator(content).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        self._checkbutton(
            content,
            "analysis.standardize_columns",
            variable=self.columns_var,
        ).grid(row=row, column=0, sticky="w")
        self.column_case_var = tk.StringVar()
        self._choice_combo(
            content,
            self.column_case_var,
            "column_case",
            "lower",
            state="readonly",
            width=20,
        ).grid(row=row, column=1, sticky="w", padx=12)
        row += 1
        self.polish_var = tk.BooleanVar()
        self._checkbutton(
            content,
            "analysis.remove_polish",
            variable=self.polish_var,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=(24, 0))
        row += 1

        self._label(content, "analysis.text_columns").grid(
            row=row,
            column=0,
            sticky="w",
        )
        self.text_columns_var = tk.StringVar()
        ttk.Entry(content, textvariable=self.text_columns_var, width=60).grid(row=row, column=1, sticky="ew", padx=12)
        row += 1
        self._label(content, "analysis.case").grid(
            row=row,
            column=0,
            sticky="w",
        )
        self.text_case_var = tk.StringVar()
        self._choice_combo(
            content,
            self.text_case_var,
            "text_case",
            "none",
            state="readonly",
            width=20,
        ).grid(row=row, column=1, sticky="w", padx=12)
        row += 1
        ttk.Separator(content).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        self._checkbutton(
            content,
            "analysis.standardize_dates",
            variable=self.dates_var,
        ).grid(row=row, column=0, sticky="w")
        self.date_columns_var = tk.StringVar()
        ttk.Entry(content, textvariable=self.date_columns_var, width=60).grid(row=row, column=1, sticky="ew", padx=12)
        row += 1
        self._label(content, "analysis.date_format").grid(
            row=row,
            column=0,
            sticky="w",
        )
        self.date_format_var = tk.StringVar(value="%Y.%m.%d")
        ttk.Combobox(
            content,
            textvariable=self.date_format_var,
            values=("%Y.%m.%d", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y.%m.%d %H:%M"),
            width=22,
        ).grid(row=row, column=1, sticky="w", padx=12)
        row += 1
        self._label(
            content,
            "analysis.columns_hint",
            style="Muted.TLabel",
        ).grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        ttk.Separator(content).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        self._label(content, "analysis.email_columns").grid(
            row=row,
            column=0,
            sticky="w",
        )
        self.email_columns_var = tk.StringVar()
        ttk.Entry(content, textvariable=self.email_columns_var, width=60).grid(row=row, column=1, sticky="ew", padx=12)
        row += 1
        self._label(content, "analysis.invalid_emails").grid(
            row=row,
            column=0,
            sticky="w",
        )
        self.email_action_var = tk.StringVar()
        self._choice_combo(
            content,
            self.email_action_var,
            "email_action",
            "keep",
            state="readonly",
            width=28,
        ).grid(row=row, column=1, sticky="w", padx=12)
        row += 1
        ttk.Separator(content).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        self._label(content, "analysis.missing_columns").grid(
            row=row,
            column=0,
            sticky="w",
        )
        self.missing_columns_var = tk.StringVar()
        ttk.Entry(content, textvariable=self.missing_columns_var, width=60).grid(row=row, column=1, sticky="ew", padx=12)
        row += 1
        self._label(content, "analysis.missing_strategy").grid(
            row=row,
            column=0,
            sticky="w",
        )
        self.missing_strategy_var = tk.StringVar()
        self._choice_combo(
            content,
            self.missing_strategy_var,
            "missing_strategy",
            "keep",
            state="readonly",
            width=28,
        ).grid(row=row, column=1, sticky="w", padx=12)
        row += 1
        self._label(content, "analysis.replacement").grid(
            row=row,
            column=0,
            sticky="w",
        )
        self.missing_replacement_var = tk.StringVar(
            value=self._t("choice.missing_text")
        )
        ttk.Entry(content, textvariable=self.missing_replacement_var, width=30).grid(row=row, column=1, sticky="w", padx=12)
        content.columnconfigure(1, weight=1)

        self.preview_button = self._button(
            frame,
            "analysis.preview",
            style="Accent.TButton",
            command=self._preview_changes,
        )
        self.preview_button.pack(side="right", pady=(12, 0))

    def _build_preview_step(self) -> None:
        frame = self._new_step("preview")
        top = ttk.Frame(frame)
        top.pack(fill="x")
        self._label(top, "preview.title", style="Title.TLabel").pack(side="left")
        self._button(
            top,
            "preview.back",
            command=lambda: self.show_step("analysis"),
        ).pack(side="right")
        self.preview_summary = ttk.Label(frame, text="", style="Muted.TLabel")
        self.preview_summary.pack(fill="x", pady=(6, 12))
        self.change_tree = CSVTree(frame, height=18)
        self.change_tree.pack(fill="both", expand=True)
        self.warning_text = tk.Text(frame, height=4, wrap="word", state="disabled")
        self.warning_text.pack(fill="x", pady=(12, 0))
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(12, 0))
        self._button(
            actions,
            "preview.reset",
            command=self._reset_changes,
        ).pack(side="left")
        self.approve_button = self._button(
            actions,
            "preview.approve",
            style="Accent.TButton",
            command=self._approve_changes,
        )
        self.approve_button.pack(side="right")

    def _build_export_step(self) -> None:
        frame = self._new_step("export")
        self._label(frame, "export.title", style="Title.TLabel").pack(anchor="w")
        self._label(
            frame,
            "export.description",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(6, 20))
        self.export_form = ttk.Frame(frame, padding=20, style="Card.TFrame")
        self.export_form.pack(fill="x")
        self._label(self.export_form, "export.output").grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.output_path_var = tk.StringVar()
        self.output_path_var.trace_add("write", self._on_output_path_changed)
        ttk.Entry(
            self.export_form,
            textvariable=self.output_path_var,
        ).grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self._button(
            self.export_form,
            "export.choose",
            command=self._choose_output,
        ).grid(row=1, column=1)

        self.csv_export_options = self._label_frame(
            self.export_form,
            "export.csv_settings",
            padding=(12, 8),
        )
        self.csv_export_options.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(14, 0),
        )
        self._label(
            self.csv_export_options,
            "data.separator",
        ).grid(row=0, column=0, sticky="w")
        self.export_separator_var = tk.StringVar()
        self.export_separator_combo = self._choice_combo(
            self.csv_export_options,
            self.export_separator_var,
            "separator",
            "semicolon",
            state="readonly",
            width=20,
        )
        self.export_separator_combo.grid(
            row=1,
            column=0,
            sticky="w",
            padx=(0, 18),
        )
        self._label(
            self.csv_export_options,
            "export.encoding",
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
        self._checkbutton(
            self.csv_export_options,
            "export.include_index",
            variable=self.include_index_var,
        ).grid(
            row=2,
            column=0,
            sticky="w",
            pady=(14, 0),
        )
        self._label(
            self.csv_export_options,
            "export.empty_value",
        ).grid(row=2, column=1, sticky="w", pady=(14, 0))
        self.empty_value_var = tk.StringVar()
        ttk.Entry(
            self.csv_export_options,
            textvariable=self.empty_value_var,
            width=24,
        ).grid(row=3, column=1, sticky="w")

        self.xlsx_export_options = self._label_frame(
            self.export_form,
            "export.xlsx_settings",
            padding=(12, 8),
        )
        self.xlsx_export_options.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(14, 0),
        )
        self._label(
            self.xlsx_export_options,
            "export.sheet_name",
        ).grid(row=0, column=0, sticky="w")
        self.output_sheet_var = tk.StringVar(
            value=self._t("choice.cleaned_sheet")
        )
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
        self._button(
            actions,
            "export.back",
            command=lambda: self.show_step("preview"),
        ).pack(side="left")
        self.open_folder_button = self._button(
            actions,
            "export.open_folder",
            command=self._open_output_folder,
            state="disabled",
        )
        self.open_folder_button.pack(side="right", padx=(8, 0))
        self.open_report_button = self._button(
            actions,
            "export.open_report",
            command=self._open_report,
            state="disabled",
        )
        self.open_report_button.pack(side="right", padx=(8, 0))
        self.save_button = self._button(
            actions,
            "export.save",
            style="Accent.TButton",
            command=self._save,
        )
        self.save_button.pack(side="right")

    def _refresh_dynamic_text(self) -> None:
        if DRAG_DROP_AVAILABLE:
            self.drop_hint_var.set(self._t("file.drop_hint"))
        else:
            self.drop_hint_var.set(self._t("file.drop_unavailable"))
        self._render_loaded_text()
        self._render_analysis_text()
        self._render_preview_text()
        if self.last_output:
            self.export_status.configure(
                text=self._t(
                    "export.saved_status",
                    name=self.last_output.name,
                )
            )

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
        if isinstance(
            error,
            (LocalizedError, LocalizedValueError),
        ):
            message = error.render(self.language)
        elif isinstance(error, (FileLoadError, ExportError, ValueError)):
            message = str(error)
        elif isinstance(error, MemoryError):
            message = self._t("error.memory")
        else:
            message = self._t("error.unexpected")
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
            title=self._t("dialog.choose_data"),
            filetypes=(
                (self._t("dialog.data_files"), "*.csv *.xlsx"),
                ("CSV", "*.csv"),
                ("Excel", "*.xlsx"),
            ),
        )
        if selected:
            self._load(selected)

    def _load(self, path: str, **options: Any) -> None:
        self._run_task(
            self._t("busy.loading"),
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
            separator_code = next(
                (
                    code
                    for code, value in SEPARATORS.items()
                    if value == loaded.separator
                ),
                "comma",
            )
            self.separator_var.set(
                self._choice_label("separator", separator_code)
            )
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
        self._render_loaded_text()
        self.data_tree.show_frame(loaded.data)
        self.show_step("data")

    def _render_loaded_text(self) -> None:
        if not self.loaded:
            return
        loaded = self.loaded
        hint_key = "data.xlsx_hint" if loaded.sheets else "data.csv_hint"
        self.data_options_hint.configure(text=self._t(hint_key))
        size = human_file_size(loaded.path.stat().st_size)
        self.file_info.configure(
            text=self._t(
                "data.info",
                name=loaded.path.name,
                size=size,
                rows=len(loaded.data),
                columns=len(loaded.data.columns),
            )
        )

    def _reload_with_options(self) -> None:
        if not self.loaded:
            return
        if self.loaded.path.suffix.lower() == ".csv":
            self._load(
                str(self.loaded.path),
                encoding=self.encoding_var.get(),
                separator=SEPARATORS[
                    self._choice_code("separator", self.separator_var.get())
                ],
            )
        else:
            self._load(str(self.loaded.path), sheet_name=self.sheet_var.get())

    def _analyze(self) -> None:
        if not self.loaded:
            return
        self._run_task(
            self._t("busy.analyzing"),
            lambda: analyze_data(self.loaded.data),
            self._on_analyzed,
        )

    def _on_analyzed(self, analysis: AnalysisResult) -> None:
        self.analysis = analysis
        self._render_analysis_text(initialize=True)
        self.show_step("analysis")

    def _render_analysis_text(self, *, initialize: bool = False) -> None:
        if not self.analysis:
            return
        analysis = self.analysis
        total = sum(item.count for item in analysis.issues)
        self.analysis_summary.configure(
            text=self._t(
                "analysis.summary",
                rows=analysis.rows,
                columns=analysis.columns,
                total=total,
            )
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
            columns = (
                ", ".join(issue.columns[:5])
                or self._t("analysis.whole_dataset")
            )
            self.issue_labels[issue.key].configure(
                text=self._t(
                    "analysis.issue_count",
                    count=issue.count,
                    columns=columns,
                )
            )
            if initialize:
                variables[issue.key].set(issue.count > 0)
        if initialize:
            self.date_columns_var.set(", ".join(analysis.date_columns))
            self.dates_var.set(bool(analysis.date_columns))
            self.email_columns_var.set(", ".join(analysis.email_columns))
            self.missing_columns_var.set(", ".join(analysis.missing_by_column))
        selected_key = self._selected_issue_key()
        visible_issues = [issue for issue in analysis.issues if issue.count > 0]
        issue_names = [self._t(issue.name) for issue in visible_issues]
        self.issue_example_combo.configure(values=issue_names)
        if selected_key and any(
            issue.key == selected_key for issue in visible_issues
        ):
            selected_issue = next(
                issue for issue in visible_issues if issue.key == selected_key
            )
            self.issue_example_var.set(self._t(selected_issue.name))
        else:
            self.issue_example_var.set(issue_names[0] if issue_names else "")
        self._show_issue_examples()

    def _selected_issue_key(self) -> str | None:
        if not self.analysis:
            return None
        selected = self.issue_example_var.get()
        for issue in self.analysis.issues:
            for language in ("en", "pl"):
                if translate(language, issue.name) == selected:
                    return issue.key
        return None

    def _show_issue_examples(self, _event: tk.Event[Any] | None = None) -> None:
        if not self.analysis:
            return
        selected_key = self._selected_issue_key()
        issue = self.analysis.issue(selected_key) if selected_key else None
        lines: list[str] = []
        if issue:
            if issue.examples:
                for example in issue.examples:
                    row = example.get("row", "")
                    values = ", ".join(
                        f"{key}={value}" for key, value in example.items() if key != "row"
                    )
                    lines.append(
                        self._t("analysis.row", row=row, values=values)
                    )
            elif issue.columns:
                lines.append(
                    self._t(
                        "analysis.columns",
                        columns=", ".join(issue.columns),
                    )
                )
        if not lines:
            lines.append(self._t("analysis.no_examples"))
        self.issue_examples_text.configure(state="normal")
        self.issue_examples_text.delete("1.0", "end")
        self.issue_examples_text.insert("1.0", "\n".join(lines))
        self.issue_examples_text.configure(state="disabled")

    @staticmethod
    def _columns_from(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def _build_config(self) -> CleaningConfig:
        duplicate_keep = self._choice_code(
            "duplicate_keep",
            self.duplicate_keep_var.get(),
        )
        case_mode = self._choice_code(
            "text_case",
            self.text_case_var.get(),
        )
        missing_strategy = self._choice_code(
            "missing_strategy",
            self.missing_strategy_var.get(),
        )
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
            column_case=self._choice_code(
                "column_case",
                self.column_case_var.get(),
            ),
            remove_polish_characters=self.polish_var.get(),
            text_case_columns=self._columns_from(self.text_columns_var.get()),
            text_case_mode=case_mode,
            date_columns=self._columns_from(self.date_columns_var.get()) if self.dates_var.get() else [],
            date_output_format=self.date_format_var.get(),
            email_columns=self._columns_from(self.email_columns_var.get()) if self.email_var.get() else [],
            invalid_email_action=self._choice_code(
                "email_action",
                self.email_action_var.get(),
            ),
            missing_strategy=missing_strategy if self.missing_var.get() else "keep",
            missing_replacement=self.missing_replacement_var.get(),
            missing_columns=self._columns_from(self.missing_columns_var.get()),
        )

    def _preview_changes(self) -> None:
        if not self.loaded:
            return
        config = self._build_config()
        self._run_task(
            self._t("busy.preview"),
            lambda: clean_data(self.loaded.data, config),
            self._on_preview_ready,
        )

    def _on_preview_ready(self, result: OperationResult) -> None:
        self.cleaning_result = result
        self.unsaved_changes = True
        self._render_preview_text()
        self.show_step("preview")

    def _render_preview_text(self) -> None:
        if not self.cleaning_result:
            return
        result = self.cleaning_result
        shown = len(result.changes)
        self.preview_summary.configure(
            text=self._t(
                "preview.summary",
                changes=result.total_changes,
                shown=shown,
                rows=result.removed_rows,
                columns=result.removed_columns,
            )
        )
        self.change_tree.show_changes(result.changes, self._t)
        self.warning_text.configure(state="normal")
        self.warning_text.delete("1.0", "end")
        warnings = [
            warning.render(self.language)
            if isinstance(warning, LocalizedMessage)
            else str(warning)
            for warning in result.warnings[:20]
        ]
        self.warning_text.insert(
            "1.0",
            "\n".join(warnings) if warnings else self._t("preview.no_warnings"),
        )
        self.warning_text.configure(state="disabled")

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
            title=self._t("dialog.save_copy"),
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
            messagebox.showwarning(
                "CSV Cleaner",
                self._t("dialog.choose_output"),
                parent=self,
            )
            return
        target = Path(value).expanduser().resolve()
        overwrite = False
        if target == self.loaded.path:
            confirmed = messagebox.askyesno(
                self._t("dialog.overwrite_source_title"),
                self._t("dialog.overwrite_source"),
                parent=self,
                default=messagebox.NO,
            )
            if not confirmed:
                return
            overwrite = True
        elif target.exists():
            overwrite = messagebox.askyesno(
                self._t("dialog.exists_title"),
                self._t("dialog.exists"),
                parent=self,
                default=messagebox.NO,
            )
            if not overwrite:
                return

        result_to_save = self.cleaning_result
        source_path = self.loaded.path
        rows_before = len(self.loaded.data)
        columns_before = len(self.loaded.data.columns)
        export_separator = SEPARATORS[
            self._choice_code(
                "separator",
                self.export_separator_var.get(),
            )
        ]
        export_encoding = self.export_encoding_var.get()
        include_index = self.include_index_var.get()
        empty_value = self.empty_value_var.get()
        output_sheet = self.output_sheet_var.get()
        report_language = self.language

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
                language=report_language,
            )
            return output, save_reports(report, output)

        self._run_task(
            self._t("busy.saving"),
            save_all,
            self._on_saved,
        )

    def _on_saved(self, value: tuple[Path, tuple[Path, Path]]) -> None:
        self.last_output, self.last_reports = value
        self.unsaved_changes = False
        self.export_status.configure(
            text=self._t(
                "export.saved_status",
                name=self.last_output.name,
            )
        )
        self.open_folder_button.configure(state="normal")
        self.open_report_button.configure(state="normal")
        messagebox.showinfo(
            "CSV Cleaner",
            self._t("dialog.saved"),
            parent=self,
        )

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError:
            messagebox.showerror(
                "CSV Cleaner",
                self._t("dialog.open_failed", path=path),
                parent=self,
            )

    def _open_output_folder(self) -> None:
        if self.last_output:
            self._open_path(self.last_output.parent)

    def _open_report(self) -> None:
        if self.last_reports:
            self._open_path(self.last_reports[0])

    def _on_close(self) -> None:
        if self.unsaved_changes:
            confirmed = messagebox.askyesno(
                self._t("dialog.unsaved_title"),
                self._t("dialog.unsaved"),
                parent=self,
                default=messagebox.NO,
            )
            if not confirmed:
                return
        self.destroy()

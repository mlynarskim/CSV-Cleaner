from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from csv_cleaner.i18n import LocalizedError, LocalizedValueError
from csv_cleaner.utils.encoding import detect_encoding
from csv_cleaner.utils.file_helpers import validate_input_path


class FileLoadError(LocalizedError):
    """A safe, user facing file loading error."""


@dataclass(slots=True)
class LoadedFile:
    path: Path
    data: pd.DataFrame
    encoding: str | None = None
    separator: str | None = None
    sheet_name: str | None = None
    sheets: list[str] | None = None


def detect_separator(path: Path, encoding: str) -> str:
    try:
        with path.open("r", encoding=encoding, errors="strict", newline="") as stream:
            sample = stream.read(65_536)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except (csv.Error, UnicodeError):
        counts = {item: sample.count(item) for item in ",;\t|"} if "sample" in locals() else {}
        if counts and max(counts.values()) > 0:
            return max(counts, key=counts.get)  # type: ignore[arg-type]
        raise FileLoadError("error.separator")


def list_excel_sheets(path: str | Path) -> list[str]:
    try:
        candidate = validate_input_path(path)
    except LocalizedValueError as exc:
        raise FileLoadError(exc.key, **exc.values) from exc
    try:
        with pd.ExcelFile(candidate, engine="openpyxl") as workbook:
            return workbook.sheet_names
    except Exception as exc:
        raise FileLoadError("error.workbook") from exc


def load_file(
    path: str | Path,
    *,
    encoding: str | None = None,
    separator: str | None = None,
    sheet_name: str | None = None,
) -> LoadedFile:
    try:
        candidate = validate_input_path(path)
        if candidate.suffix.lower() == ".csv":
            selected_encoding = encoding or detect_encoding(candidate)[0]
            selected_separator = separator or detect_separator(candidate, selected_encoding)
            frame = pd.read_csv(
                candidate,
                encoding=selected_encoding,
                sep=selected_separator,
                keep_default_na=True,
                skip_blank_lines=False,
            )
            if len(frame.columns) == 0:
                raise FileLoadError("error.no_headers")
            return LoadedFile(
                path=candidate,
                data=frame,
                encoding=selected_encoding,
                separator=selected_separator,
            )

        sheets = list_excel_sheets(candidate)
        selected_sheet = sheet_name or sheets[0]
        frame = pd.read_excel(candidate, sheet_name=selected_sheet, engine="openpyxl")
        return LoadedFile(
            path=candidate,
            data=frame,
            sheet_name=selected_sheet,
            sheets=sheets,
        )
    except FileLoadError:
        raise
    except UnicodeError as exc:
        raise FileLoadError("error.encoding") from exc
    except PermissionError as exc:
        raise FileLoadError("error.permission_read") from exc
    except pd.errors.EmptyDataError as exc:
        raise FileLoadError("error.no_data") from exc
    except pd.errors.ParserError as exc:
        raise FileLoadError("error.parser") from exc
    except LocalizedValueError as exc:
        raise FileLoadError(exc.key, **exc.values) from exc
    except (OSError, ValueError) as exc:
        raise FileLoadError("error.file_read") from exc

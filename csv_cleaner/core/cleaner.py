from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from typing import Any

import pandas as pd

from csv_cleaner.core.analyzer import blank_mask
from csv_cleaner.core.validator import invalid_email_mask, parse_date_value
from csv_cleaner.models.cleaning_config import CleaningConfig
from csv_cleaner.models.operation_result import ChangeRecord, OperationResult


MAX_PREVIEW_CHANGES = 500


def _display(value: Any) -> str:
    return "" if pd.isna(value) else str(value)


def _record(
    result: OperationResult,
    row: Any,
    column: str,
    before: Any,
    after: Any,
    operation: str,
) -> None:
    result.total_changes += 1
    if len(result.changes) < MAX_PREVIEW_CHANGES:
        result.changes.append(
            ChangeRecord(row=row, column=column, before=_display(before), after=_display(after), operation=operation)
        )


def _standardize_name(name: str, config: CleaningConfig) -> str:
    value = re.sub(r"\s+", " ", str(name).strip())
    value = value.replace(" ", "_")
    if config.remove_polish_characters:
        value = "".join(
            character
            for character in unicodedata.normalize("NFKD", value)
            if not unicodedata.combining(character)
        )
    if config.remove_special_characters:
        value = re.sub(r"[^\w]+", "_", value, flags=re.UNICODE)
        value = re.sub(r"_+", "_", value).strip("_")
    if config.column_case == "lower":
        value = value.lower()
    elif config.column_case == "upper":
        value = value.upper()
    return value or "column"


def _unique_names(names: list[str]) -> list[str]:
    result: list[str] = []
    counts: dict[str, int] = {}
    for name in names:
        count = counts.get(name, 0)
        candidate = name if count == 0 else f"{name}_{count + 1}"
        while candidate in result:
            count += 1
            candidate = f"{name}_{count + 1}"
        counts[name] = count + 1
        result.append(candidate)
    return result


def _replace_text(
    frame: pd.DataFrame,
    columns: list[str],
    transform: Callable[[str], str],
    result: OperationResult,
    operation: str,
) -> int:
    changed = 0
    for column in columns:
        if column not in frame.columns:
            continue
        for index, value in frame[column].items():
            if pd.isna(value) or not isinstance(value, str):
                continue
            updated = transform(value)
            if updated != value:
                frame.at[index, column] = updated
                _record(result, index, str(column), value, updated, operation)
                changed += 1
    return changed


def clean_data(source: pd.DataFrame, config: CleaningConfig) -> OperationResult:
    frame = source.copy(deep=True)
    result = OperationResult(data=frame)

    if config.remove_empty_rows:
        mask = blank_mask(frame).all(axis=1)
        count = int(mask.sum())
        for index in frame.index[mask]:
            _record(result, index, "", "pusty wiersz", "usunięto", "Usunięcie pustego wiersza")
        frame = frame.loc[~mask].copy()
        result.removed_rows += count
        result.operations["empty_rows_removed"] = count

    if config.remove_empty_columns and len(frame.columns):
        mask = blank_mask(frame).all(axis=0)
        columns = [str(item) for item in frame.columns[mask]]
        for column in columns:
            _record(result, "", column, "pusta kolumna", "usunięto", "Usunięcie pustej kolumny")
        frame = frame.drop(columns=columns)
        result.removed_columns += len(columns)
        result.operations["empty_columns_removed"] = len(columns)

    if config.trim_whitespace:
        text_columns = [str(item) for item in frame.select_dtypes(include=["object", "string"]).columns]

        def trim(value: str) -> str:
            updated = value.strip()
            return re.sub(r"\s+", " ", updated) if config.collapse_internal_spaces else updated

        count = _replace_text(frame, text_columns, trim, result, "Czyszczenie odstępów")
        result.operations["trimmed_values"] = count

    if config.duplicates.enabled:
        subset = [column for column in config.duplicates.columns if column in frame.columns] or None
        keep: str | bool = config.duplicates.keep
        if keep == "remove_all":
            keep = False
        if keep == "mark":
            result.operations["duplicates_found"] = int(frame.duplicated(subset=subset, keep=False).sum())
        else:
            mask = frame.duplicated(subset=subset, keep=keep)
            count = int(mask.sum())
            for index in frame.index[mask]:
                _record(result, index, "", "duplikat", "usunięto", "Usunięcie duplikatu")
            frame = frame.loc[~mask].copy()
            result.removed_rows += count
            result.operations["duplicates_removed"] = count

    available_case_columns = [column for column in config.text_case_columns if column in frame.columns]
    case_transforms: dict[str, Callable[[str], str]] = {
        "lower": str.lower,
        "upper": str.upper,
        "capitalize": str.capitalize,
        "title": str.title,
    }
    if config.text_case_mode in case_transforms:
        count = _replace_text(
            frame,
            available_case_columns,
            case_transforms[config.text_case_mode],
            result,
            "Standaryzacja wielkości liter",
        )
        result.operations["case_values_changed"] = count

    converted = 0
    for column in config.date_columns:
        if column not in frame.columns:
            continue
        for index, value in frame[column].items():
            if pd.isna(value) or not str(value).strip():
                continue
            parsed = parse_date_value(value)
            if parsed is None:
                result.warnings.append(f"Nie przekształcono daty w kolumnie {column}, wiersz {index}.")
                continue
            updated = parsed.strftime(config.date_output_format)
            if updated != str(value):
                frame.at[index, column] = updated
                _record(result, index, column, value, updated, "Standaryzacja daty")
                converted += 1
    if config.date_columns:
        result.operations["dates_converted"] = converted

    invalid_found = 0
    for column in config.email_columns:
        if column not in frame.columns:
            continue
        mask = invalid_email_mask(frame[column])
        invalid_found += int(mask.sum())
        if config.invalid_email_action == "empty":
            for index in frame.index[mask]:
                value = frame.at[index, column]
                frame.at[index, column] = pd.NA
                _record(result, index, column, value, "", "Usunięcie nieprawidłowego adresu")
    if config.email_columns:
        result.operations["invalid_emails_found"] = invalid_found

    columns = [column for column in config.missing_columns if column in frame.columns]
    for column in columns:
        mask = blank_mask(frame[[column]])[column]
        if not mask.any() or config.missing_strategy == "keep":
            continue
        if config.missing_strategy == "drop":
            for index in frame.index[mask]:
                _record(result, index, column, "", "usunięto wiersz", "Usunięcie wiersza z brakiem")
            count = int(mask.sum())
            frame = frame.loc[~mask].copy()
            result.removed_rows += count
            result.operations["missing_rows_removed"] = result.operations.get("missing_rows_removed", 0) + count
            continue
        replacement: Any = config.missing_replacement
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if config.missing_strategy == "zero":
            replacement = 0
        elif config.missing_strategy == "mean":
            replacement = numeric.mean()
        elif config.missing_strategy == "median":
            replacement = numeric.median()
        elif config.missing_strategy == "mode":
            modes = frame.loc[~mask, column].mode()
            if modes.empty:
                result.warnings.append(f"Nie można wyznaczyć dominanty dla kolumny {column}.")
                continue
            replacement = modes.iloc[0]
        if pd.isna(replacement):
            result.warnings.append(f"Nie można wyznaczyć wartości dla kolumny {column}.")
            continue
        for index in frame.index[mask]:
            frame.at[index, column] = replacement
            _record(result, index, column, "", replacement, "Uzupełnienie braku")
        result.operations["missing_values_filled"] = result.operations.get("missing_values_filled", 0) + int(mask.sum())

    if config.standardize_column_names:
        old_names = [str(item) for item in frame.columns]
        new_names = _unique_names([_standardize_name(item, config) for item in old_names])
        for old, new in zip(old_names, new_names):
            if old != new:
                _record(result, "nagłówek", old, old, new, "Standaryzacja nazwy kolumny")
        frame.columns = new_names
        result.operations["column_names_changed"] = sum(a != b for a, b in zip(old_names, new_names))

    result.data = frame.reset_index(drop=True)
    return result

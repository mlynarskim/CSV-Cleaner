from __future__ import annotations

import re
from typing import Any

import pandas as pd

from csv_cleaner.core.validator import invalid_email_mask, parse_date_value
from csv_cleaner.models.analysis_result import AnalysisResult, DataIssue


def blank_mask(frame: pd.DataFrame) -> pd.DataFrame:
    mask = frame.isna()
    text_columns = frame.select_dtypes(include=["object", "string"]).columns
    for column in text_columns:
        mask[column] = mask[column] | frame[column].astype("string").str.strip().eq("")
    return mask


def _examples(frame: pd.DataFrame, mask: pd.Series, limit: int = 5) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, row in frame.loc[mask].head(limit).iterrows():
        values = {
            str(column): (None if pd.isna(value) else str(value))
            for column, value in row.items()
        }
        records.append({"row": int(index) + 2 if isinstance(index, int) else str(index), **values})
    return records


def analyze_data(frame: pd.DataFrame) -> AnalysisResult:
    blanks = blank_mask(frame)
    empty_rows = blanks.all(axis=1)
    empty_columns = [str(column) for column in frame.columns[blanks.all(axis=0)]]
    duplicate_mask = frame.duplicated(keep=False)

    whitespace_by_column: dict[str, int] = {}
    for column in frame.select_dtypes(include=["object", "string"]).columns:
        series = frame[column].dropna().astype(str)
        count = int(
            (
                series.ne(series.str.strip())
                | series.str.contains(r"\s{2,}", regex=True, na=False)
            ).sum()
        )
        if count:
            whitespace_by_column[str(column)] = count

    missing_by_column = {
        str(column): int(blanks[column].sum())
        for column in frame.columns
        if int(blanks[column].sum()) > 0
    }

    date_columns: list[str] = []
    email_columns: list[str] = []
    invalid_email_count = 0
    invalid_email_examples: list[dict[str, Any]] = []
    for column in frame.select_dtypes(include=["object", "string"]).columns:
        values = frame[column].dropna().astype(str).str.strip()
        values = values[values.ne("")]
        if values.empty:
            continue
        name = str(column)
        date_hint = bool(re.search(r"date|data|czas|time", name, re.IGNORECASE))
        date_like = values.str.contains(r"\d{1,4}[./-]\d{1,2}[./-]\d{1,4}", regex=True).mean()
        if date_hint or date_like >= 0.6:
            parsed_count = int(values.map(lambda value: parse_date_value(value) is not None).sum())
            if parsed_count / len(values) >= 0.6:
                date_columns.append(name)
        email_hint = "mail" in name.lower() or values.str.contains("@", regex=False).mean() >= 0.5
        if email_hint:
            email_columns.append(name)
            invalid = invalid_email_mask(frame[column])
            invalid_email_count += int(invalid.sum())
            invalid_email_examples.extend(_examples(frame, invalid, 5))

    issues = [
        DataIssue(
            "empty_rows",
            "Całkowicie puste wiersze",
            int(empty_rows.sum()),
            examples=_examples(frame, empty_rows),
            proposed_operation="Usuń puste wiersze",
        ),
        DataIssue(
            "empty_columns",
            "Całkowicie puste kolumny",
            len(empty_columns),
            columns=empty_columns,
            proposed_operation="Usuń puste kolumny",
        ),
        DataIssue(
            "duplicates",
            "Powtarzające się rekordy",
            int(duplicate_mask.sum()),
            columns=[str(item) for item in frame.columns],
            examples=_examples(frame, duplicate_mask),
            proposed_operation="Usuń duplikaty",
        ),
        DataIssue(
            "whitespace",
            "Wartości ze zbędnymi odstępami",
            sum(whitespace_by_column.values()),
            columns=list(whitespace_by_column),
            proposed_operation="Oczyść odstępy",
        ),
        DataIssue(
            "missing",
            "Brakujące wartości",
            sum(missing_by_column.values()),
            columns=list(missing_by_column),
            proposed_operation="Uzupełnij brakujące wartości",
        ),
        DataIssue(
            "invalid_emails",
            "Nieprawidłowe adresy poczty",
            invalid_email_count,
            columns=email_columns,
            examples=invalid_email_examples[:5],
            proposed_operation="Waliduj adresy poczty",
        ),
    ]
    return AnalysisResult(
        rows=len(frame),
        columns=len(frame.columns),
        issues=issues,
        missing_by_column=missing_by_column,
        date_columns=date_columns,
        email_columns=email_columns,
    )

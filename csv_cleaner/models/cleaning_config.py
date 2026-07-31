from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DuplicateConfig:
    enabled: bool = False
    columns: list[str] = field(default_factory=list)
    keep: str = "first"


@dataclass(slots=True)
class CleaningConfig:
    remove_empty_rows: bool = False
    remove_empty_columns: bool = False
    trim_whitespace: bool = False
    collapse_internal_spaces: bool = False
    duplicates: DuplicateConfig = field(default_factory=DuplicateConfig)
    standardize_column_names: bool = False
    column_case: str = "lower"
    remove_special_characters: bool = True
    remove_polish_characters: bool = False
    text_case_columns: list[str] = field(default_factory=list)
    text_case_mode: str = "none"
    date_columns: list[str] = field(default_factory=list)
    date_output_format: str = "%Y.%m.%d"
    email_columns: list[str] = field(default_factory=list)
    invalid_email_action: str = "keep"
    missing_strategy: str = "keep"
    missing_replacement: str = ""
    missing_columns: list[str] = field(default_factory=list)

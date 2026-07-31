from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DataIssue:
    key: str
    name: str
    count: int
    columns: list[str] = field(default_factory=list)
    examples: list[dict[str, Any]] = field(default_factory=list)
    proposed_operation: str = ""


@dataclass(slots=True)
class AnalysisResult:
    rows: int
    columns: int
    issues: list[DataIssue] = field(default_factory=list)
    missing_by_column: dict[str, int] = field(default_factory=dict)
    date_columns: list[str] = field(default_factory=list)
    email_columns: list[str] = field(default_factory=list)

    def issue(self, key: str) -> DataIssue | None:
        return next((item for item in self.issues if item.key == key), None)

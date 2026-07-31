from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(slots=True)
class ChangeRecord:
    row: Any
    column: str
    before: str
    after: str
    operation: str


@dataclass(slots=True)
class OperationResult:
    data: pd.DataFrame
    changes: list[ChangeRecord] = field(default_factory=list)
    total_changes: int = 0
    operations: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    removed_rows: int = 0
    removed_columns: int = 0

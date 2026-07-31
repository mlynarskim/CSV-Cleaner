from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from csv_cleaner.models.operation_result import OperationResult


def build_report(
    source_file: str | Path,
    output_file: str | Path,
    rows_before: int,
    columns_before: int,
    result: OperationResult,
) -> dict[str, Any]:
    return {
        "source_file": str(Path(source_file).name),
        "output_file": str(Path(output_file).name),
        "processed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "rows_before": rows_before,
        "rows_after": len(result.data),
        "columns_before": columns_before,
        "columns_after": len(result.data.columns),
        "operations": result.operations,
        "changed_values": result.total_changes,
        "removed_rows": result.removed_rows,
        "removed_columns": result.removed_columns,
        "warnings": result.warnings,
        "errors": [],
    }


def save_reports(report: dict[str, Any], output_file: str | Path) -> tuple[Path, Path]:
    output = Path(output_file)
    base = output.with_suffix("")
    json_path = base.with_name(f"{base.name}_report.json")
    text_path = base.with_name(f"{base.name}_report.txt")
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "CSV Cleaner: raport operacji",
        "",
        f"Plik źródłowy: {report['source_file']}",
        f"Plik wynikowy: {report['output_file']}",
        f"Data operacji: {report['processed_at']}",
        f"Wiersze: {report['rows_before']} → {report['rows_after']}",
        f"Kolumny: {report['columns_before']} → {report['columns_after']}",
        f"Zarejestrowane zmiany: {report['changed_values']}",
        f"Usunięte wiersze: {report['removed_rows']}",
        f"Usunięte kolumny: {report['removed_columns']}",
        "",
        "Wykonane operacje:",
    ]
    operations = report["operations"]
    lines.extend(f"  {name}: {count}" for name, count in operations.items())
    lines.extend(["", "Ostrzeżenia:"])
    warnings = report["warnings"]
    lines.extend(f"  {warning}" for warning in warnings)
    if not warnings:
        lines.append("  Brak")
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return text_path, json_path

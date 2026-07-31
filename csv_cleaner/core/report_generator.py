from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from csv_cleaner.i18n import DEFAULT_LANGUAGE, LocalizedMessage, translate
from csv_cleaner.models.operation_result import OperationResult


def build_report(
    source_file: str | Path,
    output_file: str | Path,
    rows_before: int,
    columns_before: int,
    result: OperationResult,
    *,
    language: str = DEFAULT_LANGUAGE,
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
        "warnings": [
            warning.render(language)
            if isinstance(warning, LocalizedMessage)
            else str(warning)
            for warning in result.warnings
        ],
        "errors": [],
        "language": language,
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
    language = str(report.get("language", DEFAULT_LANGUAGE))
    lines = [
        translate(language, "report.title"),
        "",
        translate(language, "report.source", value=report["source_file"]),
        translate(language, "report.output", value=report["output_file"]),
        translate(language, "report.date", value=report["processed_at"]),
        translate(
            language,
            "report.rows",
            before=report["rows_before"],
            after=report["rows_after"],
        ),
        translate(
            language,
            "report.columns",
            before=report["columns_before"],
            after=report["columns_after"],
        ),
        translate(language, "report.changes", value=report["changed_values"]),
        translate(language, "report.removed_rows", value=report["removed_rows"]),
        translate(
            language,
            "report.removed_columns",
            value=report["removed_columns"],
        ),
        "",
        translate(language, "report.operations"),
    ]
    operations = report["operations"]
    lines.extend(
        f"  {translate(language, f'summary.{name}')}: {count}"
        for name, count in operations.items()
    )
    lines.extend(["", translate(language, "report.warnings")])
    warnings = report["warnings"]
    lines.extend(f"  {warning}" for warning in warnings)
    if not warnings:
        lines.append(f"  {translate(language, 'report.none')}")
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return text_path, json_path

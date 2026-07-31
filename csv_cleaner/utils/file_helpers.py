from __future__ import annotations

from pathlib import Path

from csv_cleaner.i18n import LocalizedValueError


SUPPORTED_EXTENSIONS = {".csv", ".xlsx"}
MAX_FILE_SIZE = 100 * 1024 * 1024


def validate_input_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.exists():
        raise LocalizedValueError("error.path_missing")
    if not candidate.is_file():
        raise LocalizedValueError("error.path_not_file")
    if candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise LocalizedValueError("error.extension")
    if candidate.stat().st_size == 0:
        raise LocalizedValueError("error.empty_file")
    if candidate.stat().st_size > MAX_FILE_SIZE:
        raise LocalizedValueError("error.file_too_large")
    return candidate


def human_file_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"

from __future__ import annotations

from pathlib import Path


SUPPORTED_EXTENSIONS = {".csv", ".xlsx"}
MAX_FILE_SIZE = 100 * 1024 * 1024


def validate_input_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.exists():
        raise ValueError("Wybrany plik nie istnieje.")
    if not candidate.is_file():
        raise ValueError("Wybrana ścieżka nie prowadzi do pliku.")
    if candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("Obsługiwane są wyłącznie pliki CSV oraz XLSX.")
    if candidate.stat().st_size == 0:
        raise ValueError("Wybrany plik jest pusty.")
    if candidate.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("Plik przekracza limit 100 MB.")
    return candidate


def human_file_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"

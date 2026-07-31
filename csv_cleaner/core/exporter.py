from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd


class ExportError(Exception):
    """A safe, user facing export error."""


def export_data(
    frame: pd.DataFrame,
    output_path: str | Path,
    *,
    separator: str = ",",
    encoding: str = "utf-8-sig",
    include_index: bool = False,
    empty_value: str = "",
    sheet_name: str = "Cleaned Data",
    overwrite: bool = False,
) -> Path:
    target = Path(output_path).expanduser().resolve()
    if target.suffix.lower() not in {".csv", ".xlsx"}:
        raise ExportError("Format wyniku musi być CSV albo XLSX.")
    if target.exists() and not overwrite:
        raise ExportError("Plik wynikowy już istnieje.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not os.access(target.parent, os.W_OK):
        raise ExportError("Brak uprawnień do zapisu w wybranym katalogu.")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}_",
        suffix=target.suffix,
        dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        if target.suffix.lower() == ".csv":
            frame.to_csv(
                temporary,
                sep=separator,
                encoding=encoding,
                index=include_index,
                na_rep=empty_value,
            )
        else:
            frame.to_excel(
                temporary,
                sheet_name=(sheet_name.strip() or "Cleaned Data")[:31],
                index=include_index,
                engine="openpyxl",
            )
        os.replace(temporary, target)
        return target
    except PermissionError as exc:
        raise ExportError(
            "Nie można zapisać pliku. Zamknij go w innym programie i spróbuj ponownie."
        ) from exc
    except OSError as exc:
        raise ExportError("Wystąpił błąd podczas zapisu pliku.") from exc
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)

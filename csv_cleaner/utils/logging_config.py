from __future__ import annotations

import logging
from pathlib import Path


def configure_logging() -> Path:
    log_dir = Path.home() / ".csv_cleaner"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "csv_cleaner.log"
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    return log_path

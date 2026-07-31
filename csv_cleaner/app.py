from __future__ import annotations

import logging

from csv_cleaner.ui.main_window import MainWindow
from csv_cleaner.utils.logging_config import configure_logging


def main() -> None:
    configure_logging()
    try:
        application = MainWindow()
        application.mainloop()
    except Exception:
        logging.getLogger(__name__).exception("Fatal application error")
        raise


if __name__ == "__main__":
    main()

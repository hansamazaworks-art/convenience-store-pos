"""Convenience Store POS - program start.

Run from Command Prompt inside the project folder:
    .venv\\Scripts\\python.exe main.py
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from config.settings import SettingsError, load_settings
from database.connection import Database
from ui.app_controller import AppController
from ui.styles import APP_STYLESHEET
from utils.logging_setup import setup_logging

log = logging.getLogger("pos")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Convenience Store POS")
    app.setStyle("Fusion")  # same look on every Windows version
    app.setStyleSheet(APP_STYLESHEET)

    try:
        settings = load_settings()
    except SettingsError as exc:
        QMessageBox.critical(None, "Settings problem", str(exc))
        return 2

    setup_logging(settings.log_dir, settings.log_level, [settings.db.password])

    def excepthook(exc_type, exc, tb):
        log.critical("Unexpected error", exc_info=(exc_type, exc, tb))
        QMessageBox.critical(
            None, "Unexpected error",
            "Something went wrong. The details were saved to logs\\pos.log.\n"
            "Please tell the administrator.",
        )
    sys.excepthook = excepthook

    log.info("Starting POS; database %s", settings.db.safe_description())
    controller = AppController(app, settings, Database(settings.db))
    # Start inside the event loop, so "quit" works even from the first dialogs.
    QTimer.singleShot(0, controller.start)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

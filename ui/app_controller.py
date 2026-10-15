"""Decides which window is shown: system check -> first-time setup -> login -> main."""
from __future__ import annotations

import logging

from PySide6.QtWidgets import QApplication, QWidget

from config.settings import Settings
from database.connection import Database
from models.user import Session
from services.container import Services
from ui.dialogs.account_dialogs import ChangePasswordDialog, FirstAdminDialog
from ui.widgets.common import run
from ui.windows.login_window import LoginWindow
from ui.windows.main_window import MainWindow
from ui.windows.startup_window import StartupWindow

log = logging.getLogger(__name__)


class AppController:
    def __init__(self, app: QApplication, settings: Settings, db: Database) -> None:
        self.app = app
        self.settings = settings
        self.services = Services.build(db, settings)
        self.window: QWidget | None = None  # keep a reference so it is not garbage-collected

    def _show(self, window: QWidget, maximized: bool = False) -> None:
        old = self.window
        self.window = window
        window.showMaximized() if maximized else window.show()
        if old is not None and old is not window:
            old.hide()
            old.deleteLater()

    # ----------------------------------------------------------------- flow
    def start(self) -> None:
        if self.services.system.check().ok:
            self._after_database_ok()
        else:
            self._show(StartupWindow(self.services.system, self.settings.store_name,
                                     on_ready=self._after_database_ok))

    def _after_database_ok(self) -> None:
        try:                        # the daily backup must never stop the store from opening
            self.services.backups.auto_backup_if_due()
        except Exception:  # noqa: BLE001 - shown on the dashboard and in Store settings
            log.exception("Automatic backup failed")
        ok, needs_admin = run(None, self.services.auth.needs_first_admin)
        if not ok:
            return self.start()
        if needs_admin:
            dlg = FirstAdminDialog(self.services)
            if not dlg.exec() or dlg.session is None:
                self.app.quit()
                return
            self.open_main(dlg.session)
        else:
            self.show_login()

    def show_login(self) -> None:
        ok, s = run(None, self.services.settings.get)
        name = s.store_name if ok else self.settings.store_name
        self._show(LoginWindow(self.services, name, on_success=self._on_login))

    def _on_login(self, session: Session) -> None:
        if session.must_change_password:
            dlg = ChangePasswordDialog(self.services, session, self.window, forced=True)
            if not dlg.exec():
                self.services.auth.logout(session)
                return  # stay on the login screen
            session = dlg.session
        self.open_main(session)

    def open_main(self, session: Session) -> None:
        self._show(MainWindow(self.services, session, on_logout=self.show_login), maximized=True)

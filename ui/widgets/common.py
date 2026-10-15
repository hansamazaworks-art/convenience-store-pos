"""Small reusable pieces used by every screen."""
from __future__ import annotations

import logging
import secrets
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from database.connection import DatabaseError
from services.errors import AuthError, NotFound, PermissionDenied, ServiceError, ValidationError

log = logging.getLogger(__name__)


def card(parent: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(parent, objectName="Card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(10)
    return frame, lay


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def button(text: str, on_click: Callable | None = None, name: str | None = None,
           shortcut: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if on_click:
        b.clicked.connect(on_click)
    if shortcut:
        b.setShortcut(shortcut)
        b.setToolTip(f"Shortcut: {shortcut}")
    b.setCursor(Qt.PointingHandCursor)
    return b


def password_field(placeholder: str = "") -> QLineEdit:
    f = QLineEdit()
    f.setEchoMode(QLineEdit.Password)
    f.setPlaceholderText(placeholder)
    f.setMaxLength(72)
    return f


def page_header(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 4)
    lay.setSpacing(2)
    lay.addWidget(label(title, "PageTitle"))
    if subtitle:
        lay.addWidget(label(subtitle, "Muted", wrap=True))
    return w


def button_row(*buttons: QWidget, stretch_first: bool = True) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    if stretch_first:
        row.addStretch()
    for b in buttons:
        row.addWidget(b)
    if not stretch_first:
        row.addStretch()
    return row


def generate_temporary_password() -> str:
    """Easy to read aloud: e.g. 'Kq7m-3RtX'. No look-alike characters."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
    a = "".join(secrets.choice(alphabet) for _ in range(4))
    b = "".join(secrets.choice(alphabet) for _ in range(4))
    return f"{a}-{b}"


def error_message(exc: BaseException) -> tuple[str, str]:
    """(title, message) suitable for a store operator."""
    if isinstance(exc, PermissionDenied):
        return "Not allowed", exc.user_message
    if isinstance(exc, AuthError):
        return "Login problem", exc.user_message
    if isinstance(exc, ValidationError):
        return "Please check", exc.user_message
    if isinstance(exc, NotFound):
        return "Not found", exc.user_message
    if isinstance(exc, ServiceError):
        return "Problem", exc.user_message
    if isinstance(exc, DatabaseError):
        return "Database problem", exc.user_message
    log.error("Unexpected error", exc_info=(type(exc), exc, exc.__traceback__))
    return ("Unexpected error",
            "Something went wrong. The details were saved to logs\\pos.log.\n"
            "Please tell the administrator.")


def show_error(parent: QWidget | None, exc: BaseException) -> None:
    title, msg = error_message(exc)
    QMessageBox.warning(parent, title, msg)


def run(parent: QWidget | None, fn: Callable[..., Any], *args, **kwargs) -> tuple[bool, Any]:
    """Call a service; on error show a friendly message. Returns (ok, result)."""
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        return True, fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - every error is shown to the user
        QApplication.restoreOverrideCursor()
        show_error(parent, exc)
        return False, None
    finally:
        if QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()


def confirm(parent: QWidget | None, title: str, text: str, yes_text: str = "Yes") -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Question)
    yes = box.addButton(yes_text, QMessageBox.AcceptRole)
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.setDefaultButton(yes)
    box.exec()
    return box.clickedButton() is yes


def info(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)

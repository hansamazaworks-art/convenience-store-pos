"""Login screen."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLineEdit, QVBoxLayout, QWidget

from models.user import Session
from services.container import Services
from ui.widgets.common import button, card, error_message, label, password_field


class LoginWindow(QWidget):
    def __init__(self, services: Services, store_name: str,
                 on_success: Callable[[Session], None]) -> None:
        super().__init__(objectName="LoginBackground")
        self.services = services
        self.on_success = on_success
        self.setWindowTitle(f"{store_name} - Log in")
        self.setMinimumSize(520, 460)

        box, lay = card()
        box.setFixedWidth(400)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(12)
        lay.addWidget(label(store_name, "Title", wrap=True))
        lay.addWidget(label("Log in to the point of sale", "Muted"))
        lay.addSpacing(6)

        self.username = QLineEdit(placeholderText="Username")
        self.username.setMaxLength(50)
        self.password = password_field("Password")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        form.setVerticalSpacing(6)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        lay.addLayout(form)

        self.error = label("", "ErrorBox", wrap=True)
        self.error.hide()
        lay.addWidget(self.error)

        self.login_btn = button("Log in", self.attempt, "Primary")
        self.login_btn.setMinimumHeight(40)
        lay.addWidget(self.login_btn)

        self.username.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self.attempt)

        outer = QVBoxLayout(self)
        outer.addStretch()
        outer.addWidget(box, alignment=Qt.AlignHCenter)
        outer.addStretch()
        self.username.setFocus()

    def attempt(self) -> None:
        self.login_btn.setEnabled(False)
        self.error.hide()
        try:
            session = self.services.auth.login(self.username.text(), self.password.text())
        except Exception as exc:  # noqa: BLE001
            _, msg = error_message(exc)
            self.error.setText(msg)
            self.error.show()
            self.password.clear()
            self.password.setFocus()
            return
        finally:
            self.login_btn.setEnabled(True)
        self.password.clear()
        self.on_success(session)

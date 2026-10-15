"""Shown only when the database cannot be used (MySQL stopped, updates pending,
wrong password...). Explains what to do and lets the user try again."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QVBoxLayout, QWidget

from services.system_service import SystemService
from ui.widgets.common import button, card, label


class StartupWindow(QMainWindow):
    def __init__(self, system: SystemService, store_name: str,
                 on_ready: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.system = system
        self.on_ready = on_ready
        self.setWindowTitle(f"{store_name} - POS")
        self.resize(580, 360)

        box, inner = card()
        inner.setContentsMargins(28, 24, 28, 24)
        inner.addWidget(label(store_name, "Title"))
        inner.addWidget(label("Point of Sale - system check", "Muted"))
        self.status = label("", wrap=True)
        self.details = label("", "Muted", wrap=True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        inner.addWidget(self.status)
        inner.addWidget(self.details)
        inner.addStretch()

        self.retry_btn = button("Check connection again", self.retry, "Primary")
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(button("Close", self.close))
        buttons.addWidget(self.retry_btn)
        inner.addLayout(buttons)

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addWidget(box)
        self.setCentralWidget(root)
        self.refresh()

    def refresh(self) -> bool:
        result = self.system.check()
        if result.ok:
            self.status.setObjectName("StatusOk")
            self.status.setText("✔  Connected to the database")
        else:
            self.status.setObjectName("StatusError")
            self.status.setText("✖  Cannot use the database")
        self.details.setText(result.summary)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        return result.ok

    def retry(self) -> None:
        if self.refresh() and self.on_ready:
            self.on_ready()

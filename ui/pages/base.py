"""Base class for pages shown in the main window."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from models.user import Session
from services.container import Services
from ui.widgets.common import page_header


class Page(QWidget):
    title = ""
    subtitle = ""

    def __init__(self, services: Services, session: Session) -> None:
        super().__init__(objectName="Page")
        self.services = services
        self.session = session
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(28, 24, 28, 24)
        self.lay.setSpacing(16)
        self.lay.addWidget(page_header(self.title, self.subtitle))

    def on_show(self) -> None:
        """Called every time the page is opened (refresh data here)."""

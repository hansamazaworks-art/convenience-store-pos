"""Input fields that only accept valid money / quantities (no floats anywhere)."""
from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QLineEdit


class MoneyEdit(QLineEdit):
    """Accepts amounts like 1250 or 1250.50. text() is passed to the service as-is."""

    def __init__(self, placeholder: str = "0.00") -> None:
        super().__init__()
        self.setValidator(QRegularExpressionValidator(QRegularExpression(r"^\d{0,7}(\.\d{0,2})?$")))
        self.setPlaceholderText(placeholder)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)


class QuantityEdit(QLineEdit):
    """Accepts 12 or 2.5 (up to 3 decimals)."""

    def __init__(self, placeholder: str = "0") -> None:
        super().__init__()
        self.setValidator(QRegularExpressionValidator(QRegularExpression(r"^\d{0,9}(\.\d{0,3})?$")))
        self.setPlaceholderText(placeholder)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

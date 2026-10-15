"""Read-only tables used by the inventory, purchasing, shift and report screens."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from ui.styles import C

RIGHT = Qt.AlignRight | Qt.AlignVCenter
RED = QColor(C["danger"])
AMBER = QColor(C["warning"])


def make_table(cols: list[str], stretch: int = 1, row_height: int = 32) -> QTableWidget:
    t = QTableWidget(0, len(cols))
    t.setHorizontalHeaderLabels(cols)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().hide()
    t.verticalHeader().setDefaultSectionSize(row_height)
    hh = t.horizontalHeader()
    hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    hh.setSectionResizeMode(QHeaderView.ResizeToContents)
    if 0 <= stretch < len(cols):
        hh.setSectionResizeMode(stretch, QHeaderView.Stretch)
    return t


def fill_table(t: QTableWidget, rows: list[list], right_cols: set[int] = frozenset(),
               colors: list[QColor | None] | None = None) -> None:
    """rows: lists of text. colors: optional text colour per row."""
    t.setRowCount(len(rows))
    for r, vals in enumerate(rows):
        color = colors[r] if colors else None
        for c, v in enumerate(vals):
            item = QTableWidgetItem("" if v is None else str(v))
            if c in right_cols:
                item.setTextAlignment(RIGHT)
            if color is not None:
                item.setForeground(color)
            t.setItem(r, c, item)


def selected_row(t: QTableWidget) -> int | None:
    rows = t.selectionModel().selectedRows()
    return rows[0].row() if rows else None


def qty(value) -> str:
    """12.000 -> '12', 2.500 -> '2.5'."""
    if value is None:
        return ""
    d = Decimal(value).normalize()
    return f"{d:f}" if d != 0 else "0"

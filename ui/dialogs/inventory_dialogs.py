"""Dialogs for the inventory screens: adjust stock, movement ledger, stock count sheet."""
from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog, QHBoxLayout, QLineEdit, QRadioButton,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from services.inventory_service import ADJUST_REASONS, StockRow
from ui.dialogs.account_dialogs import _FormDialog
from ui.widgets.common import button, button_row, confirm, info, label, run
from ui.widgets.inputs import QuantityEdit
from ui.widgets.tables import AMBER, RED, RIGHT, fill_table, make_table, qty
from utils.money import format_money


class AdjustStockDialog(_FormDialog):
    """Remove damaged / expired / lost items, or add found items, with a reason."""

    def __init__(self, services, session, row: StockRow, parent: QWidget | None = None) -> None:
        super().__init__(parent, "Adjust stock",
                         f"{row.name}\nIn stock now: {qty(row.quantity)} {row.unit_code}", "Save")
        self.services, self.session, self.row = services, session, row
        self.token = str(uuid.uuid4())   # same dialog saved twice = saved once
        self.result = None
        self.reason = QComboBox()
        for code, (text, _, direction) in ADJUST_REASONS.items():
            arrow = " (remove)" if direction < 0 else " (add)" if direction > 0 else ""
            self.reason.addItem(text + arrow, code)
        self.add_radio = QRadioButton("Add to stock")
        self.remove_radio = QRadioButton("Remove from stock")
        self.remove_radio.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.add_radio)
        grp.addButton(self.remove_radio)
        self.direction_row = QWidget()
        dl = QHBoxLayout(self.direction_row)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(self.remove_radio)
        dl.addWidget(self.add_radio)
        dl.addStretch()
        self.quantity = QuantityEdit()
        self.note = QLineEdit(placeholderText="Optional, e.g. 'dropped while stocking'")
        self.note.setMaxLength(200)
        self.preview = label("", "Muted")
        self.form.addRow("Reason", self.reason)
        self.form.addRow("", self.direction_row)
        self.form.addRow(f"Quantity ({row.unit_code})", self.quantity)
        self.form.addRow("Note", self.note)
        self.form.addRow(self.preview)
        self.reason.currentIndexChanged.connect(self._update)
        self.quantity.textChanged.connect(self._update)
        self.add_radio.toggled.connect(self._update)
        self._update()
        self.quantity.setFocus()

    def _signed(self) -> str:
        code = self.reason.currentData()
        direction = ADJUST_REASONS[code][2]
        if direction == 0:
            direction = 1 if self.add_radio.isChecked() else -1
        text = self.quantity.text().strip() or "0"
        return text if direction > 0 else f"-{text}"

    def _update(self) -> None:
        direction = ADJUST_REASONS[self.reason.currentData()][2]
        self.direction_row.setVisible(direction == 0)
        self.note.setPlaceholderText("Required: what was wrong?" if direction == 0
                                     else "Optional, e.g. 'dropped while stocking'")
        try:
            change = Decimal(self._signed())
        except InvalidOperation:
            change = Decimal(0)
        self.preview.setText(f"Stock after saving: {qty(self.row.quantity + change)} {self.row.unit_code}"
                             if change else "")

    def submit(self) -> None:
        self.result = self.services.inventory.adjust(self.session, self.row.product_id, self._signed(),
                                                     self.reason.currentData(), self.note.text(),
                                                     self.token)


class MovementsDialog(QDialog):
    """Every stock change for one product, newest first (the stock 'ledger')."""

    def __init__(self, services, session, row: StockRow, symbol: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Stock movements - {row.name}")
        self.resize(900, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.addWidget(label(row.name, "PageTitle"))
        lay.addWidget(label(f"In stock now: {qty(row.quantity)} {row.unit_code}", "SectionTitle"))
        show_cost = row.cost_price is not None
        cols = ["Date & time", "Type", "Change", "Balance", "Reference / note", "By"]
        if show_cost:
            cols.insert(4, "Unit cost")
        self.table = make_table(cols, stretch=len(cols) - 2)
        ok, rows = run(self, services.inventory.movements, session, row.product_id)
        rows = rows if ok else []
        data, colors = [], []
        for m in rows:
            change = Decimal(m["quantity"])
            vals = [m["created_at"].strftime("%d %b %Y %H:%M"), m["label"],
                    ("+" if change > 0 else "") + qty(change), qty(m["balance_after"]),
                    m["note"] or "", m["user_name"] or ""]
            if show_cost:
                vals.insert(4, format_money(m["unit_cost"], symbol))
            data.append(vals)
            colors.append(RED if change < 0 and m["movement_type"] != "sale" else None)
        fill_table(self.table, data, {2, 3, 4} if show_cost else {2, 3}, colors)
        lay.addWidget(self.table, 1)
        lay.addWidget(label(f"{len(rows)} movement{'s' if len(rows) != 1 else ''} "
                            "(newest first). Movements are never edited or deleted.", "Muted"))
        lay.addLayout(button_row(button("Close", self.accept, "Primary")))


class CountSheetDialog(QDialog):
    """Type the counted quantities. Scan a barcode in the search box to jump to an item."""

    COL_COUNTED = 4

    def __init__(self, services, session, count_id: int, parent=None) -> None:
        super().__init__(parent)
        self.services, self.session, self.count_id = services, session, count_id
        self.resize(940, 640)
        self.dirty = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        self.title = label("", "PageTitle")
        lay.addWidget(self.title)
        self.status = label("", "Muted", wrap=True)
        lay.addWidget(self.status)
        bar = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Scan barcode or type a name to find the item…")
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._jump)
        bar.addWidget(self.search, 1)
        lay.addLayout(bar)
        self.table = make_table(["Product", "Barcode / SKU", "Unit", "System qty", "Counted",
                                 "Difference"], stretch=0)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.itemChanged.connect(self._changed)
        lay.addWidget(self.table, 1)
        lay.addWidget(label("Leave a product empty if you did not count it - its stock will not "
                            "change. Type 0 if there are none on the shelf.", "Muted", wrap=True))
        self.save_btn = button("Save (keep counting later)", self.save)
        self.post_btn = button("Finish count and update stock", self.post, "Primary")
        lay.addLayout(button_row(button("Close", self.close_sheet), self.save_btn, self.post_btn))
        self.load()

    def load(self) -> None:
        ok, data = run(self, self.services.inventory.get_count, self.session, self.count_id)
        if not ok:
            return
        head, self.lines = data["count"], data["lines"]
        self.editable = head["status"] == "draft"
        self.setWindowTitle(f"Stock count {head['count_no']}")
        self.title.setText(f"Stock count {head['count_no']}")
        status = {"draft": "In progress", "posted": "Finished - stock was updated",
                  "cancelled": "Cancelled"}[head["status"]]
        self.status.setText(status + (f"  ·  {head['note']}" if head["note"] else ""))
        self.save_btn.setVisible(self.editable)
        self.post_btn.setVisible(self.editable)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.lines))
        for r, l in enumerate(self.lines):
            system = l["current_qty"] if self.editable else l["system_qty"]
            counted = l["counted_qty"]
            vals = [l["name"], l["barcode"] or l["sku"], l["unit_code"], qty(system),
                    qty(counted) if counted is not None else "", ""]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c >= 3:
                    item.setTextAlignment(RIGHT)
                if c != self.COL_COUNTED or not self.editable:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, item)
            self._show_difference(r)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers if self.editable
                                   else QAbstractItemView.NoEditTriggers)
        self.table.blockSignals(False)
        self.dirty = False
        self._update_status()

    def _system(self, r: int) -> Decimal:
        l = self.lines[r]
        return Decimal(l["current_qty"] if self.editable else (l["system_qty"] or 0))

    def _show_difference(self, r: int) -> None:
        text = self.table.item(r, self.COL_COUNTED).text().strip()
        cell = self.table.item(r, 5)
        if not text:
            cell.setText("")
            return
        try:
            diff = Decimal(text) - self._system(r)
        except InvalidOperation:
            cell.setText("?")
            return
        cell.setText(("+" if diff > 0 else "") + qty(diff) if diff else "OK")
        cell.setForeground(RED if diff < 0 else AMBER if diff > 0 else self.table.palette().text().color())

    def _changed(self, item: QTableWidgetItem) -> None:
        if item.column() == self.COL_COUNTED:
            self.table.blockSignals(True)
            self._show_difference(item.row())
            self.table.blockSignals(False)
            self.dirty = True
            self._update_status()

    def _update_status(self) -> None:
        n = sum(1 for r in range(self.table.rowCount())
                if self.table.item(r, self.COL_COUNTED).text().strip())
        self.post_btn.setText(f"Finish count and update stock ({n} counted)")

    def _filter(self, text: str) -> None:
        words = text.lower().split()
        for r, l in enumerate(self.lines):
            hay = f"{l['name']} {l['barcode'] or ''} {l['sku']}".lower()
            self.table.setRowHidden(r, not all(w in hay for w in words))

    def _jump(self) -> None:
        """Enter in the search box: exact barcode/SKU first, else the first visible row."""
        code = self.search.text().strip()
        exact = [r for r, l in enumerate(self.lines) if code and code in (l["barcode"], l["sku"])]
        visible = [r for r in range(len(self.lines)) if not self.table.isRowHidden(r)]
        target = (exact or visible or [None])[0]
        if target is None:
            return
        if exact:
            self.search.blockSignals(True)
            self.search.clear()          # ready for the next scan
            self.search.blockSignals(False)
            self._filter("")
        self.table.setCurrentCell(target, self.COL_COUNTED)
        self.table.scrollToItem(self.table.item(target, 0))
        if self.editable:
            self.table.editItem(self.table.item(target, self.COL_COUNTED))

    def values(self) -> dict[int, str]:
        return {int(l["product_id"]): self.table.item(r, self.COL_COUNTED).text()
                for r, l in enumerate(self.lines)}

    def save(self) -> bool:
        ok, _ = run(self, self.services.inventory.save_counts, self.session, self.count_id, self.values())
        if ok:
            self.dirty = False
        return ok

    def post(self) -> None:
        if not self.save():
            return
        if not confirm(self, "Finish stock count",
                       "Update the stock to the counted quantities?\n\nProducts you left empty "
                       "are not changed. This cannot be undone (a new count can correct it).",
                       "Update stock"):
            return
        ok, res = run(self, self.services.inventory.post_count, self.session, self.count_id)
        if ok:
            info(self, "Stock updated",
                 f"{res['counted']} products counted, {res['changed']} had a different quantity "
                 "and were corrected.")
            self.load()

    def close_sheet(self) -> None:
        if self.editable and self.dirty:
            if confirm(self, "Save counts?", "Save the quantities you typed before closing?", "Save"):
                if not self.save():
                    return
        self.accept()

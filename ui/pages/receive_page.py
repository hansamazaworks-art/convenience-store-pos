"""Receive stock: record what you bought (scan items, type quantity and what you paid)."""
from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QHBoxLayout, QLineEdit,
    QTableWidgetItem, QVBoxLayout,
)

from ui.dialogs.pos_dialogs import ProductPickerDialog
from ui.pages.base import Page
from ui.widgets.common import button, button_row, card, confirm, info, label, run
from ui.widgets.tables import AMBER, RED, RIGHT, fill_table, make_table, qty, selected_row
from utils.money import ZERO, format_money, to_money

COL_QTY, COL_COST, COL_TOTAL = 2, 3, 4


def _dec(text: str) -> Decimal | None:
    try:
        d = Decimal(str(text).strip().replace(",", ""))
        return d if d.is_finite() else None
    except InvalidOperation:
        return None


class DeliveriesDialog(QDialog):
    """Past deliveries; double-click to see the items."""

    def __init__(self, services, session, symbol: str, parent=None) -> None:
        super().__init__(parent)
        self.services, self.session, self.symbol = services, session, symbol
        self.setWindowTitle("Past deliveries")
        self.resize(900, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.addWidget(label("Past deliveries", "PageTitle"))
        bar = QHBoxLayout()
        self.date_from = QDateEdit(QDate.currentDate().addDays(-30), calendarPopup=True)
        self.date_to = QDateEdit(QDate.currentDate(), calendarPopup=True)
        for d in (self.date_from, self.date_to):
            d.setDisplayFormat("dd MMM yyyy")
        bar.addWidget(label("From"))
        bar.addWidget(self.date_from)
        bar.addWidget(label("To"))
        bar.addWidget(self.date_to)
        bar.addWidget(button("Show", self.refresh, "Primary"))
        bar.addStretch()
        lay.addLayout(bar)
        self.table = make_table(["No.", "Date", "Supplier", "Invoice / DR no.", "Lines", "Total",
                                 "Recorded by"], stretch=2)
        self.table.doubleClicked.connect(lambda _: self.open_detail())
        lay.addWidget(self.table, 1)
        self.summary = label("", "SectionTitle")
        lay.addWidget(self.summary)
        lay.addLayout(button_row(button("Open", self.open_detail), button("Close", self.accept, "Primary")))
        self.rows = []
        self.refresh()

    def refresh(self) -> None:
        ok, rows = run(self, self.services.purchasing.receipts, self.session,
                       self.date_from.date().toPython(), self.date_to.date().toPython())
        if not ok:
            return
        self.rows = rows
        m = lambda v: format_money(v, self.symbol)  # noqa: E731
        fill_table(self.table, [[r["receipt_no"], r["received_at"].strftime("%d %b %Y %H:%M"),
                                 r["supplier_name"] or "—", r["reference"] or "", str(r["line_count"]),
                                 m(r["total"]), r["received_by_name"]] for r in rows], {4, 5})
        self.summary.setText(f"{len(rows)} deliveries  ·  Total {m(sum((r['total'] for r in rows), ZERO))}")

    def open_detail(self) -> None:
        r = selected_row(self.table)
        if r is None:
            return
        ok, d = run(self, self.services.purchasing.receipt_detail, self.session, int(self.rows[r]["id"]))
        if not ok:
            return
        head, lines = d["receipt"], d["lines"]
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Delivery {head['receipt_no']}")
        dlg.resize(820, 460)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.addWidget(label(f"Delivery {head['receipt_no']}", "PageTitle"))
        lay.addWidget(label(f"{head['received_at'].strftime('%d %b %Y %H:%M')}  ·  "
                            f"{head['supplier_name'] or 'No supplier'}"
                            + (f"  ·  Ref {head['reference']}" if head["reference"] else "")
                            + f"  ·  Recorded by {head['received_by_name']}", "Muted", wrap=True))
        m = lambda v: format_money(v, self.symbol)  # noqa: E731
        t = make_table(["#", "Product", "Qty", "Unit cost", "Total", "Average cost before → after"])
        fill_table(t, [[str(l["line_no"]), l["name"], f"{qty(l['quantity'])} {l['unit_code']}",
                        m(l["unit_cost"]), m(l["line_total"]),
                        f"{m(l['old_cost'])} → {m(l['new_cost'])}"] for l in lines], {2, 3, 4})
        lay.addWidget(t, 1)
        if head["note"]:
            lay.addWidget(label(f"Note: {head['note']}", "Muted", wrap=True))
        lay.addWidget(label(f"TOTAL {m(head['total'])}", "SectionTitle"))
        lay.addLayout(button_row(button("Close", dlg.accept, "Primary")))
        dlg.exec()


class ReceivePage(Page):
    title = "Receive stock"
    subtitle = ("Record what you bought: scan or search each item, type how many and what you paid "
                "(per piece or for the whole line). Stock and average cost update when you save.")

    def __init__(self, services, session) -> None:
        super().__init__(services, session)
        self.symbol = "₱"
        self.lines: list[dict] = []
        self.token = str(uuid.uuid4())
        self.can_see_cost = services.products.can_see_cost(session)

        top, tl = card()
        row = QHBoxLayout()
        row.setSpacing(10)
        self.supplier = QComboBox()
        self.supplier.setMinimumWidth(220)
        row.addWidget(label("Supplier"))
        row.addWidget(self.supplier)
        if session.can("suppliers.manage"):
            row.addWidget(button("+ New", self.new_supplier, "Link"))
        self.reference = QLineEdit(placeholderText="Invoice / DR no. (optional)")
        self.reference.setMaxLength(60)
        self.note = QLineEdit(placeholderText="Note (optional)")
        self.note.setMaxLength(200)
        row.addWidget(self.reference)
        row.addWidget(self.note, 1)
        tl.addLayout(row)
        self.lay.addWidget(top)

        self.scan = QLineEdit(placeholderText="Scan barcode or type product name, then Enter")
        self.scan.setStyleSheet("font-size: 13pt; padding: 8px 10px;")
        self.scan.returnPressed.connect(self.on_scan)
        self.lay.addWidget(self.scan)
        self.message = label("", "Muted", wrap=True)
        self.lay.addWidget(self.message)

        self.table = make_table(["Product", "Unit", "Qty received", f"Cost each ({self.symbol})",
                                 f"Total paid ({self.symbol})", "Selling price", ""], stretch=0)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.table.itemChanged.connect(self._edited)
        self.lay.addWidget(self.table, 1)

        foot = QHBoxLayout()
        self.total_label = label("", "PageTitle")
        foot.addWidget(self.total_label, 1)
        foot.addWidget(button("Past deliveries…", self.history))
        foot.addWidget(button("Remove line", self.remove_line))
        foot.addWidget(button("Clear", self.clear))
        self.from_drawer = QCheckBox("Paid with cash from my drawer")
        self.from_drawer.setToolTip("Takes the total out of your open shift's expected cash.")
        foot.addWidget(self.from_drawer)
        self.save_btn = button("Save delivery", self.save, "Primary", "Ctrl+S")
        foot.addWidget(self.save_btn)
        self.lay.addLayout(foot)
        self.render()

    # -------------------------------------------------------------- setup
    @property
    def has_open_delivery(self) -> bool:
        return bool(self.lines)

    def on_show(self) -> None:
        ok, s = run(self, self.services.settings.get)
        if ok:
            self.symbol = s.currency_symbol
        self._load_suppliers()
        ok, shift = run(self, self.services.shifts.current, self.session)
        self.from_drawer.setVisible(bool(ok and shift))
        if not (ok and shift):
            self.from_drawer.setChecked(False)
        self.scan.setFocus()

    def _load_suppliers(self, select: int | None = None) -> None:
        current = select if select is not None else self.supplier.currentData()
        ok, rows = run(self, self.services.purchasing.suppliers, self.session)
        self.supplier.clear()
        self.supplier.addItem("— none —", None)
        for r in rows if ok else []:
            self.supplier.addItem(r["name"], int(r["id"]))
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(current)))

    def new_supplier(self) -> None:
        from ui.pages.suppliers_page import SupplierDialog
        dlg = SupplierDialog(self.services, self.session, None, self)
        if dlg.exec():
            self._load_suppliers(dlg.saved_id)

    # -------------------------------------------------------------- lines
    def on_scan(self) -> None:
        text = self.scan.text().strip()
        if not text:
            return
        ok, product = run(self, self.services.products.find_by_code, self.session, text)
        if not ok:
            return
        if product is None:
            ok, matches = run(self, self.services.products.search, self.session, text, None, False, 50)
            if not ok:
                return
            if not matches:
                self.message.setText(f"No product found for '{text}'. Add it in Products first.")
                self.scan.selectAll()
                return
            product = matches[0]
            if len(matches) > 1:
                dlg = ProductPickerDialog(matches, self.symbol, self)
                if not dlg.exec() or dlg.chosen is None:
                    return
                product = dlg.chosen
        self.scan.clear()
        for i, l in enumerate(self.lines):
            if l["product"].id == product.id:     # scanned again: one more
                q = _dec(l["qty"]) or Decimal(0)
                l["qty"] = qty(q + 1)
                self._recalc(l, "qty")
                self.render(i, COL_QTY)
                return
        cost = product.cost_price if product.cost_price is not None else None
        line = {"product": product, "qty": "1", "cost": f"{cost:.2f}" if cost else "", "total": "",
                "mode": "unit"}
        self._recalc(line, "qty")
        self.lines.append(line)
        self.message.setText(f"Added {product.name}. Type the quantity and cost.")
        self.render(len(self.lines) - 1, COL_QTY)

    @staticmethod
    def _recalc(line: dict, changed: str) -> None:
        """Keep cost each x qty = total. Typing the total switches to 'total' mode."""
        q = _dec(line["qty"])
        if changed == "total":
            line["mode"] = "total"
        elif changed == "cost":
            line["mode"] = "unit"
        if line["mode"] == "total":
            t = _dec(line["total"])
            line["cost"] = f"{to_money(t / q):.2f}" if t is not None and q else ""
        else:
            c = _dec(line["cost"])
            line["total"] = f"{to_money(c * q):.2f}" if c is not None and q is not None else ""

    def _edited(self, item: QTableWidgetItem) -> None:
        r, c = item.row(), item.column()
        if r >= len(self.lines) or c not in (COL_QTY, COL_COST, COL_TOTAL):
            return
        key = {COL_QTY: "qty", COL_COST: "cost", COL_TOTAL: "total"}[c]
        self.lines[r][key] = item.text().strip()
        self._recalc(self.lines[r], key)
        self.render(r, c)

    def render(self, select_row: int | None = None, select_col: int = COL_QTY) -> None:
        m = lambda v: format_money(v, self.symbol)  # noqa: E731
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.lines))
        total = ZERO
        for r, l in enumerate(self.lines):
            p = l["product"]
            t = _dec(l["total"])
            total += to_money(t) if t is not None else ZERO
            cost = _dec(l["cost"])
            warn = ""
            if cost is not None and cost > p.selling_price:
                warn = "Cost is higher than the selling price!"
            vals = [p.name, p.unit_code, l["qty"], l["cost"], l["total"], m(p.selling_price), warn]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c in (COL_QTY, COL_COST, COL_TOTAL, 5):
                    item.setTextAlignment(RIGHT)
                if c not in (COL_QTY, COL_COST, COL_TOTAL):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if c == 6:
                    item.setForeground(RED)
                if c == COL_TOTAL and l["mode"] == "total" or c == COL_COST and l["mode"] == "unit":
                    item.setToolTip("Typed by you")
                elif c in (COL_COST, COL_TOTAL):
                    item.setForeground(AMBER)
                    item.setToolTip("Calculated")
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)
        n = len(self.lines)
        self.total_label.setText(f"{n} item{'s' if n != 1 else ''}  ·  Total paid {m(total)}")
        self.save_btn.setEnabled(bool(n))
        if select_row is not None and 0 <= select_row < n:
            self.table.setCurrentCell(select_row, select_col)

    def remove_line(self) -> None:
        r = self.table.currentRow()
        if 0 <= r < len(self.lines):
            self.lines.pop(r)
            self.render(min(r, len(self.lines) - 1))

    def clear(self) -> None:
        if self.lines and not confirm(self, "Clear", "Remove all lines from this delivery?", "Clear"):
            return
        self._reset()

    def _reset(self) -> None:
        self.lines = []
        self.token = str(uuid.uuid4())
        self.reference.clear()
        self.note.clear()
        self.from_drawer.setChecked(False)
        self.message.setText("")
        self.render()
        self.scan.setFocus()

    # ---------------------------------------------------------------- save
    def save(self) -> None:
        from services.purchasing_service import ReceiveLine
        if not self.lines:
            return
        lines = [ReceiveLine(l["product"].id, l["qty"],
                             l["cost"] if l["mode"] == "unit" else "",
                             l["total"] if l["mode"] == "total" else "") for l in self.lines]
        if any(not (l["cost"] or l["total"]) for l in self.lines):
            if not confirm(self, "No cost typed", "Some lines have no cost. Save them at zero cost?",
                           "Save anyway"):
                return
        ok, res = run(self, self.services.purchasing.receive, self.session, lines,
                      self.supplier.currentData(), self.reference.text(), self.note.text(), self.token,
                      self.from_drawer.isVisibleTo(self) and self.from_drawer.isChecked())
        if not ok:
            return
        info(self, "Delivery saved",
             f"Delivery {res.receipt_no} saved: {format_money(res.total, self.symbol)}.\n"
             "Stock and average costs were updated.")
        self._reset()

    def history(self) -> None:
        DeliveriesDialog(self.services, self.session, self.symbol, self).exec()

"""Past sales: search by date, sale number or item; open a sale to see details."""
from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDateEdit, QDialog, QHBoxLayout, QHeaderView, QLineEdit, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ui.pages.base import Page
from ui.widgets.common import button, button_row, label, run
from utils.money import ZERO, format_money

_RIGHT = Qt.AlignRight | Qt.AlignVCenter


def _table(cols, stretch=1):
    t = QTableWidget(0, len(cols))
    t.setHorizontalHeaderLabels(cols)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().hide()
    t.verticalHeader().setDefaultSectionSize(34)
    hh = t.horizontalHeader()
    hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    hh.setSectionResizeMode(QHeaderView.ResizeToContents)
    hh.setSectionResizeMode(stretch, QHeaderView.Stretch)
    return t


def _fill(t: QTableWidget, rows: list[list], right_cols: set[int]) -> None:
    t.setRowCount(len(rows))
    for r, vals in enumerate(rows):
        for c, v in enumerate(vals):
            item = QTableWidgetItem(v)
            if c in right_cols:
                item.setTextAlignment(_RIGHT)
            t.setItem(r, c, item)


class SaleDetailDialog(QDialog):
    def __init__(self, detail: dict, symbol: str, parent=None, on_reprint=None) -> None:
        super().__init__(parent)
        s, lines, pays = detail["sale"], detail["lines"], detail["payments"]
        self.setWindowTitle(f"Sale {s['sale_no']}")
        self.resize(820, 560)
        m = lambda v: format_money(v, symbol)  # noqa: E731
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.addWidget(label(f"Sale {s['sale_no']}", "PageTitle"))
        lay.addWidget(label(f"{s['created_at'].strftime('%d %b %Y %H:%M:%S')}  ·  Cashier: {s['cashier']}",
                            "Muted"))
        lt = _table(["#", "Item", "Qty", "Price", "Discount", "Amount"])
        _fill(lt, [[str(l["line_no"]), l["name"], f"{l['quantity'].normalize():f} {l['unit_code']}",
                    m(l["unit_price"]),
                    (f"-{m(l['line_discount'] + l['sale_discount_share'])}"
                     if l["line_discount"] + l["sale_discount_share"] else ""),
                    m(l["net_amount"])] for l in lines], {2, 3, 4, 5})
        lt.setCurrentCell(-1, -1)
        lt.setFocusPolicy(Qt.NoFocus)
        lay.addWidget(lt, 1)
        summary = f"Subtotal {m(s['subtotal'])}"
        if s["discount_total"]:
            summary += f"    ·    Discount -{m(s['discount_total'])}"
        lay.addWidget(label(summary, "Muted"))
        if s["sale_discount_reason"]:
            lay.addWidget(label(f"Sale discount: {s['sale_discount_reason']} "
                                f"(approved by {s['sale_discount_approver']})", "Muted"))
        lay.addWidget(label(f"TOTAL {m(s['total'])}", "PageTitle"))
        pay_text = "Paid: " + ", ".join(
            f"{p['method']} {m(p['amount'])}" + (f" (ref {p['reference']})" if p["reference"] else "")
            for p in pays) + f"    ·    Received {m(s['amount_paid'])}    ·    Change {m(s['change_given'])}"
        lay.addWidget(label(pay_text, "Muted", wrap=True))
        btns = []
        if on_reprint:
            btns.append(button("Receipt…", lambda: on_reprint(int(s["id"]))))
        btns.append(button("Close", self.accept, "Primary"))
        lay.addLayout(button_row(*btns))


class SalesHistoryPage(Page):
    title = "Sales history"

    def __init__(self, services, session, on_reprint=None) -> None:
        super().__init__(services, session)
        self.on_reprint = on_reprint
        self.all = session.can("pos.history")
        self.subtitle_label = label("All sales." if self.all else "Your own sales.", "Muted")
        self.lay.insertWidget(1, self.subtitle_label)
        self.rows: list[dict] = []
        self.symbol = "₱"
        bar = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Sale number, item name or barcode…")
        self.search.returnPressed.connect(self.refresh)
        self.date_from = QDateEdit(QDate.currentDate(), calendarPopup=True)
        self.date_to = QDateEdit(QDate.currentDate(), calendarPopup=True)
        for d in (self.date_from, self.date_to):
            d.setDisplayFormat("dd MMM yyyy")
        bar.addWidget(self.search, 1)
        bar.addWidget(label("From"))
        bar.addWidget(self.date_from)
        bar.addWidget(label("To"))
        bar.addWidget(self.date_to)
        bar.addWidget(button("Search", self.refresh, "Primary"))
        self.lay.addLayout(bar)
        self.table = _table(["Sale no.", "Date & time", "Cashier", "Items", "Discount", "Total", "Paid by"], 2)
        self.table.doubleClicked.connect(lambda _: self.open_sale())
        self.lay.addWidget(self.table, 1)
        foot = QHBoxLayout()
        self.summary = label("", "SectionTitle")
        foot.addWidget(self.summary, 1)
        foot.addWidget(button("Open sale", self.open_sale))
        self.lay.addLayout(foot)

    def on_show(self) -> None:
        ok, s = run(self, self.services.settings.get)
        if ok:
            self.symbol = s.currency_symbol
        self.refresh()

    def refresh(self) -> None:
        if self.date_from.date() > self.date_to.date():
            self.date_from.setDate(self.date_to.date())
        ok, rows = run(self, self.services.sales.search_sales, self.session,
                       self.date_from.date().toPython(), self.date_to.date().toPython(),
                       self.search.text())
        if not ok:
            return
        self.rows = rows
        m = lambda v: format_money(v, self.symbol)  # noqa: E731
        _fill(self.table, [[r["sale_no"], r["created_at"].strftime("%d %b %Y %H:%M"), r["cashier"],
                            f"{r['item_count'].normalize():f}",
                            f"-{m(r['discount_total'])}" if r["discount_total"] else "",
                            m(r["total"]), r["methods"] or ""] for r in rows], {3, 4, 5})
        total = sum((r["total"] for r in rows), ZERO)
        self.summary.setText(f"{len(rows)} sale{'s' if len(rows) != 1 else ''}  ·  Total {m(total)}"
                             + ("  (first 1000 shown)" if len(rows) >= 1000 else ""))

    def open_sale(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        sale_id = int(self.rows[rows[0].row()]["id"])
        ok, detail = run(self, self.services.sales.sale_detail, self.session, sale_id)
        if ok:
            SaleDetailDialog(detail, self.symbol, self, self.on_reprint).exec()

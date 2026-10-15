"""My shift (cashiers), Shifts (managers) and Expenses screens."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDateEdit, QHBoxLayout, QInputDialog

from ui.dialogs.shift_dialogs import (
    CashMovementDialog, CloseShiftDialog, ExpenseDialog, OpenShiftDialog, ShiftReportDialog,
)
from ui.pages.base import Page
from ui.widgets.common import button, card, confirm, label, run
from ui.widgets.tables import AMBER, RED, fill_table, make_table, selected_row
from utils.money import ZERO, format_money


def _date_bar(days_back: int = 6):
    d_from = QDateEdit(QDate.currentDate().addDays(-days_back), calendarPopup=True)
    d_to = QDateEdit(QDate.currentDate(), calendarPopup=True)
    for d in (d_from, d_to):
        d.setDisplayFormat("dd MMM yyyy")
    return d_from, d_to


def _diff_text(row: dict, m) -> str:
    if row["difference"] is None:
        return ""
    d = Decimal(row["difference"])
    return "exact" if d == 0 else (f"over {m(d)}" if d > 0 else f"short {m(-d)}")


class MyShiftPage(Page):
    title = "My shift"
    subtitle = "Open your shift with the starting cash, record cash in/out and expenses, close with a count."

    def __init__(self, services, session) -> None:
        super().__init__(services, session)
        self.symbol = "₱"
        self.shift = None
        box, bl = card()
        self.status = label("", "PageTitle")
        self.details = label("", "Muted", wrap=True)
        bl.addWidget(self.status)
        bl.addWidget(self.details)
        row = QHBoxLayout()
        self.open_btn = button("Open shift…", self.open_shift, "Primary")
        self.in_btn = button("Cash in…", lambda: self.movement("cash_in"))
        self.out_btn = button("Cash out…", lambda: self.movement("cash_out"))
        self.exp_btn = button("Expense from drawer…", self.expense)
        self.close_btn = button("Close shift…", self.close_shift, "Danger")
        for b in (self.open_btn, self.in_btn, self.out_btn, self.exp_btn, self.close_btn):
            b.setMinimumHeight(40)
            row.addWidget(b)
        row.addStretch()
        bl.addLayout(row)
        self.lay.addWidget(box)
        self.lay.addWidget(label("Cash in / out during this shift", "SectionTitle"))
        self.moves = make_table(["Time", "Type", "Reason", "Amount", "By", "Approved by"], stretch=2)
        self.lay.addWidget(self.moves, 1)
        self.lay.addWidget(label("My recent shifts", "SectionTitle"))
        self.history = make_table(["Shift", "Opened", "Closed", "Starting cash", "Counted", "Result"],
                                  stretch=0)
        self.history.doubleClicked.connect(lambda _: self.open_history())
        self.history_rows = []
        self.lay.addWidget(self.history, 1)

    def on_show(self) -> None:
        ok, s = run(self, self.services.settings.get)
        if ok:
            self.symbol = s.currency_symbol
        self.refresh()

    def refresh(self) -> None:
        m = lambda v: format_money(v, self.symbol)  # noqa: E731
        ok, self.shift = run(self, self.services.shifts.current, self.session)
        is_open = bool(ok and self.shift)
        self.open_btn.setVisible(not is_open)
        for b in (self.in_btn, self.out_btn, self.exp_btn, self.close_btn):
            b.setVisible(is_open)
        if is_open:
            sh = self.shift
            ok, summ = run(self, self.services.shifts.summary, self.session, int(sh["id"]))
            self.status.setText(f"Shift {sh['shift_no']} is open")
            self.details.setText(
                f"Opened {sh['opened_at'].strftime('%d %b %Y %H:%M')}  ·  Starting cash "
                f"{m(sh['opening_float'])}  ·  Sales so far: {summ.sales_count if ok else '?'}")
            ok, rows = run(self, self.services.shifts.movements, self.session, int(sh["id"]))
            fill_table(self.moves, [[r["created_at"].strftime("%H:%M"), r["label"], r["reason"] or "",
                                     m(r["amount"]), r["user_name"], r["approved_by_name"] or ""]
                                    for r in (rows if ok else [])], {3})
        else:
            self.status.setText("No open shift")
            self.details.setText("Open your shift before selling: count the cash in the drawer first.")
            self.moves.setRowCount(0)
        ok, rows = run(self, self.services.shifts.list_shifts, self.session,
                       date.today() - timedelta(days=30), date.today())
        self.history_rows = rows if ok else []
        fill_table(self.history, [[r["shift_no"], r["opened_at"].strftime("%d %b %H:%M"),
                                   r["closed_at"].strftime("%d %b %H:%M") if r["closed_at"] else "open",
                                   m(r["opening_float"]),
                                   m(r["counted_cash"]) if r["counted_cash"] is not None else "",
                                   _diff_text(r, m)] for r in self.history_rows], {3, 4})

    def open_shift(self) -> None:
        if OpenShiftDialog(self.services, self.session, self).exec():
            self.refresh()

    def movement(self, kind: str) -> None:
        if CashMovementDialog(self.services, self.session, kind, self).exec():
            self.refresh()

    def expense(self) -> None:
        if ExpenseDialog(self.services, self.session, self, drawer_only=True).exec():
            self.refresh()

    def close_shift(self) -> None:
        if not self.shift:
            return
        pos = self.window().pages.get("pos") if hasattr(self.window(), "pages") else None
        if pos is not None and pos.has_open_sale:
            self.details.setText("Finish or hold the sale in Checkout before closing the shift.")
            return
        dlg = CloseShiftDialog(self.services, self.session, self.shift, self.symbol, self)
        if dlg.exec() and dlg.result_summary:
            ShiftReportDialog(self.services, self.session, dlg.result_summary, self.symbol, self).exec()
        self.refresh()

    def open_history(self) -> None:
        r = selected_row(self.history)
        if r is None:
            return
        ok, summ = run(self, self.services.shifts.summary, self.session, int(self.history_rows[r]["id"]))
        if ok:
            ShiftReportDialog(self.services, self.session, summ, self.symbol, self).exec()


class ShiftsPage(Page):
    title = "Shifts"
    subtitle = "All cashier shifts with their cash count. Red = short, orange = over."

    def __init__(self, services, session) -> None:
        super().__init__(services, session)
        self.symbol = "₱"
        self.rows = []
        bar = QHBoxLayout()
        self.date_from, self.date_to = _date_bar()
        bar.addWidget(label("From"))
        bar.addWidget(self.date_from)
        bar.addWidget(label("To"))
        bar.addWidget(self.date_to)
        bar.addWidget(button("Show", self.refresh, "Primary"))
        bar.addStretch()
        self.lay.addLayout(bar)
        self.table = make_table(["Shift", "Cashier", "Opened", "Closed", "Starting cash", "Expected",
                                 "Counted", "Result", "Closed by"], stretch=1)
        self.table.doubleClicked.connect(lambda _: self.open_shift())
        self.lay.addWidget(self.table, 1)
        foot = QHBoxLayout()
        self.summary = label("", "SectionTitle")
        foot.addWidget(self.summary, 1)
        foot.addWidget(button("Close this shift…", self.force_close, "Danger"))
        foot.addWidget(button("Open", self.open_shift))
        self.lay.addLayout(foot)

    def on_show(self) -> None:
        ok, s = run(self, self.services.settings.get)
        if ok:
            self.symbol = s.currency_symbol
        self.refresh()

    def refresh(self) -> None:
        m = lambda v: format_money(v, self.symbol)  # noqa: E731
        ok, rows = run(self, self.services.shifts.list_shifts, self.session,
                       self.date_from.date().toPython(), self.date_to.date().toPython())
        if not ok:
            return
        self.rows = rows
        colors = []
        for r in rows:
            d = r["difference"]
            colors.append(None if d is None or d == 0 else RED if d < 0 else AMBER)
        fill_table(self.table, [[r["shift_no"], r["user_name"], r["opened_at"].strftime("%d %b %H:%M"),
                                 r["closed_at"].strftime("%d %b %H:%M") if r["closed_at"] else "OPEN",
                                 m(r["opening_float"]),
                                 m(r["expected_cash"]) if r["expected_cash"] is not None else "",
                                 m(r["counted_cash"]) if r["counted_cash"] is not None else "",
                                 _diff_text(r, m), r["closed_by_name"] or ""] for r in rows],
                   {4, 5, 6}, colors)
        net = sum((Decimal(r["difference"]) for r in rows if r["difference"] is not None), ZERO)
        n_open = sum(1 for r in rows if r["status"] == "open")
        self.summary.setText(f"{len(rows)} shifts  ·  {n_open} open  ·  Total over/short: {m(net)}")

    def _selected(self):
        r = selected_row(self.table)
        return self.rows[r] if r is not None else None

    def open_shift(self) -> None:
        row = self._selected()
        if row:
            ok, summ = run(self, self.services.shifts.summary, self.session, int(row["id"]))
            if ok:
                ShiftReportDialog(self.services, self.session, summ, self.symbol, self).exec()

    def force_close(self) -> None:
        row = self._selected()
        if not row or row["status"] != "open":
            self.summary.setText("Select an open shift first.")
            return
        if not confirm(self, "Close shift", f"Close {row['user_name']}'s shift {row['shift_no']}? "
                       "Count the cash in that drawer first.", "Continue"):
            return
        dlg = CloseShiftDialog(self.services, self.session, row, self.symbol, self)
        if dlg.exec() and dlg.result_summary:
            ShiftReportDialog(self.services, self.session, dlg.result_summary, self.symbol, self).exec()
        self.refresh()


class ExpensesPage(Page):
    title = "Expenses"
    subtitle = "Money spent on the store. Drawer expenses also reduce the cash expected in that shift."

    def __init__(self, services, session) -> None:
        super().__init__(services, session)
        self.symbol = "₱"
        self.rows = []
        bar = QHBoxLayout()
        self.date_from, self.date_to = _date_bar(29)
        bar.addWidget(label("From"))
        bar.addWidget(self.date_from)
        bar.addWidget(label("To"))
        bar.addWidget(self.date_to)
        bar.addWidget(button("Show", self.refresh, "Primary"))
        bar.addStretch()
        self.lay.addLayout(bar)
        self.table = make_table(["Date", "Kind", "Description", "Amount", "Paid from", "Recorded by",
                                 "Status"], stretch=2)
        self.lay.addWidget(self.table, 1)
        foot = QHBoxLayout()
        self.summary = label("", "SectionTitle")
        foot.addWidget(self.summary, 1)
        foot.addWidget(button("Void…", self.void, "Danger"))
        foot.addWidget(button("+ Add expense", self.add, "Primary"))
        self.lay.addLayout(foot)

    def on_show(self) -> None:
        ok, s = run(self, self.services.settings.get)
        if ok:
            self.symbol = s.currency_symbol
        self.refresh()

    def refresh(self) -> None:
        m = lambda v: format_money(v, self.symbol)  # noqa: E731
        ok, rows = run(self, self.services.expenses.list, self.session,
                       self.date_from.date().toPython(), self.date_to.date().toPython())
        if not ok:
            return
        self.rows = rows
        fill_table(self.table, [[r["expense_date"].strftime("%d %b %Y"), r["category"],
                                 r["description"] or "", m(r["amount"]),
                                 f"Drawer ({r['shift_no']})" if r["paid_from"] == "drawer" else "Other money",
                                 r["created_by_name"],
                                 "Active" if r["status"] == "active" else f"VOID: {r['void_reason']}"]
                                for r in rows], {3},
                   [None if r["status"] == "active" else RED for r in rows])
        total = sum((r["amount"] for r in rows if r["status"] == "active"), ZERO)
        self.summary.setText(f"{sum(1 for r in rows if r['status'] == 'active')} expenses  ·  Total {m(total)}")

    def add(self) -> None:
        if ExpenseDialog(self.services, self.session, self).exec():
            self.refresh()

    def void(self) -> None:
        r = selected_row(self.table)
        if r is None or self.rows[r]["status"] != "active":
            self.summary.setText("Select an active expense first.")
            return
        reason, ok = QInputDialog.getText(self, "Void expense", "Why is this expense wrong?")
        if ok:
            ok, _ = run(self, self.services.expenses.void, self.session, int(self.rows[r]["id"]), reason)
            if ok:
                self.refresh()

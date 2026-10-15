"""Shift dialogs: open, cash in/out, drawer expense, blind close, shift report."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QGridLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget,
)

from ui.dialogs.account_dialogs import _FormDialog
from ui.dialogs.pos_dialogs import authorize
from ui.widgets.common import button, button_row, label, run, show_error
from ui.widgets.inputs import MoneyEdit
from ui.widgets.tables import fill_table, make_table
from utils.money import format_money, to_money

# Philippine bills and coins, for counting the drawer.
DENOMINATIONS = ["1000", "500", "200", "100", "50", "20", "10", "5", "1", "0.25"]


class _Cancelled(Exception):
    """The manager approval window was closed: do nothing, keep the dialog open."""


class _ApprovalForm(_FormDialog):
    """A form whose submit() may ask for manager approval first (raises _Cancelled if refused)."""

    def _on_ok(self) -> None:
        self.error.hide()
        try:
            self.submit()
        except _Cancelled:
            return
        except Exception as exc:  # noqa: BLE001
            self.fail(exc)
            return
        self.accept()


class OpenShiftDialog(_FormDialog):
    def __init__(self, services, session, parent=None) -> None:
        super().__init__(parent, "Open shift",
                         "Count the cash in the drawer before you start selling (the change fund).",
                         "Open shift")
        self.services, self.session = services, session
        self.shift_id = None
        self.amount = MoneyEdit()
        self.amount.setStyleSheet("font-size: 16pt; padding: 6px;")
        self.form.addRow("Starting cash in the drawer", self.amount)
        self.amount.setFocus()

    def submit(self) -> None:
        self.shift_id = self.services.shifts.open_shift(self.session, self.amount.text() or "0")


class CashMovementDialog(_ApprovalForm):
    """Cash in (add change) or cash out (e.g. money moved to the safe)."""

    def __init__(self, services, session, kind: str, parent=None) -> None:
        title = "Cash in" if kind == "cash_in" else "Cash out"
        intro = ("Money ADDED to the drawer, e.g. more coins for change." if kind == "cash_in" else
                 "Money TAKEN OUT of the drawer, e.g. moved to the safe. For buying something, "
                 "use 'Expense' instead.")
        super().__init__(parent, title, intro, "Save")
        self.services, self.session, self.kind = services, session, kind
        self.token = str(uuid.uuid4())
        self.amount = MoneyEdit()
        self.reason = QLineEdit()
        self.reason.setMaxLength(200)
        self.reason.setPlaceholderText("Reason *")
        self.form.addRow("Amount", self.amount)
        self.form.addRow("Reason", self.reason)
        self.amount.setFocus()

    def submit(self) -> None:
        approver = authorize(self, self.services, self.session, "cash.movements",
                             f"{'Cash in' if self.kind == 'cash_in' else 'Cash out'} "
                             f"{self.amount.text() or '0'}: {self.reason.text()}")
        if approver is None:
            raise _Cancelled()
        self.services.shifts.cash_movement(
            self.session, self.kind, self.amount.text() or "0", self.reason.text(),
            approver.user_id if approver is not self.session else None, self.token)


class ExpenseDialog(_ApprovalForm):
    """An expense. Paid from the drawer (needs your open shift) or, for managers, from other money."""

    def __init__(self, services, session, parent=None, drawer_only: bool = False) -> None:
        super().__init__(parent, "Record expense",
                         "Ice, delivery, cleaning supplies… The amount is taken from the cash drawer "
                         "unless you choose 'Other money'.", "Save")
        self.services, self.session = services, session
        self.token = str(uuid.uuid4())
        self.expense_id = None
        self.category = QComboBox()
        self.category.setEditable(session.can("expenses.manage"))   # managers may type a new kind
        ok, cats = run(self, services.expenses.categories, session)
        for c in cats if ok else []:
            self.category.addItem(c["name"], int(c["id"]))
        self.category.setCurrentIndex(-1)
        if self.category.lineEdit():
            self.category.lineEdit().setPlaceholderText("Choose or type a new kind")
        self.amount = MoneyEdit()
        self.description = QLineEdit(placeholderText="Optional, e.g. '2 bags of ice'")
        self.description.setMaxLength(200)
        self.paid_from = QComboBox()
        self.paid_from.addItem("Cash drawer (this shift)", "drawer")
        if session.can("expenses.manage") and not drawer_only:
            self.paid_from.addItem("Other money (not from the drawer)", "other")
        self.form.addRow("Kind of expense", self.category)
        self.form.addRow("Amount", self.amount)
        self.form.addRow("Description", self.description)
        self.form.addRow("Paid from", self.paid_from)

    def _category_value(self):
        text = self.category.currentText().strip()
        idx = self.category.findText(text)
        if idx >= 0:
            return int(self.category.itemData(idx))
        return text

    def submit(self) -> None:
        paid_from = self.paid_from.currentData()
        approver = None
        if paid_from == "drawer":
            approver = authorize(self, self.services, self.session, "cash.movements",
                                 f"Pay {self.amount.text() or '0'} from the drawer for "
                                 f"{self.category.currentText() or 'an expense'}.")
            if approver is None:
                raise _Cancelled()
        self.expense_id = self.services.expenses.add(
            self.session, category=self._category_value(), amount=self.amount.text() or "0",
            description=self.description.text(), paid_from=paid_from, expense_date=date.today(),
            approved_by=approver.user_id if approver and approver is not self.session else None,
            token=self.token)


class CloseShiftDialog(QDialog):
    """Blind count: type (or count by bills/coins) the cash in the drawer, then close."""

    def __init__(self, services, session, shift: dict, symbol: str, parent=None) -> None:
        super().__init__(parent)
        self.services, self.session, self.shift, self.symbol = services, session, shift, symbol
        self.result_summary = None
        self.setWindowTitle("Close shift")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        lay.addWidget(label(f"Close shift {shift['shift_no']}", "SectionTitle"))
        lay.addWidget(label("Count ALL the cash in the drawer (including the starting cash). You can "
                            "count by bills and coins, or type the total.", "Muted", wrap=True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        self.counts: dict[str, QSpinBox] = {}
        for i, d in enumerate(DENOMINATIONS):
            spin = QSpinBox()
            spin.setRange(0, 99999)
            spin.setAlignment(Qt.AlignRight)
            spin.valueChanged.connect(self._from_denominations)
            self.counts[d] = spin
            text = f"{symbol}{d}" if d != "0.25" else "25¢"
            grid.addWidget(QLabel(f"{text}  ×"), i % 5, (i // 5) * 2)
            grid.addWidget(spin, i % 5, (i // 5) * 2 + 1)
        lay.addLayout(grid)
        self.counted = MoneyEdit()
        self.counted.setStyleSheet("font-size: 18pt; padding: 6px;")
        lay.addWidget(label("Total cash counted"))
        lay.addWidget(self.counted)
        self.note = QLineEdit(placeholderText="Note (optional)")
        self.note.setMaxLength(200)
        lay.addWidget(self.note)
        self.error = label("", "ErrorBox", wrap=True)
        self.error.hide()
        lay.addWidget(self.error)
        self.ok_btn = button("Close shift", self.submit, "Primary")
        lay.addLayout(button_row(button("Cancel", self.reject), self.ok_btn))

    def _from_denominations(self) -> None:
        total = sum((Decimal(d) * s.value() for d, s in self.counts.items()), Decimal(0))
        self.counted.setText(f"{to_money(total):.2f}")

    def submit(self) -> None:
        if not self.counted.text().strip():
            self.error.setText("Type the cash counted (0 if the drawer is empty).")
            self.error.show()
            return
        try:
            self.result_summary = self.services.shifts.close_shift(
                self.session, int(self.shift["id"]), self.counted.text(), self.note.text())
        except Exception as exc:  # noqa: BLE001
            from ui.widgets.common import error_message
            self.error.setText(error_message(exc)[1])
            self.error.show()
            return
        self.accept()


class ShiftReportDialog(QDialog):
    """Shift summary: sales by payment method, drawer movements, expected vs counted."""

    def __init__(self, services, session, summary, symbol: str, parent=None) -> None:
        super().__init__(parent)
        self.services, self.session, self.summary = services, session, summary
        sh = summary.shift
        self.setWindowTitle(f"Shift {sh['shift_no']}")
        self.resize(640, 620)
        m = lambda v: format_money(v, symbol)  # noqa: E731
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.addWidget(label(f"Shift {sh['shift_no']} — {sh['user_name']}", "PageTitle"))
        when = sh["opened_at"].strftime("%d %b %Y %H:%M")
        if sh["closed_at"]:
            when += " → " + sh["closed_at"].strftime("%d %b %Y %H:%M")
        lay.addWidget(label(when + ("  ·  OPEN" if sh["status"] == "open" else ""), "Muted"))
        if sh["counted_cash"] is not None:
            diff = Decimal(sh["difference"])
            word = "OVER" if diff > 0 else "SHORT" if diff < 0 else "Exact - no difference"
            big = label(f"{word}  {m(abs(diff))}" if diff else word, "PageTitle")
            big.setStyleSheet("color: %s;" % ("#B42318" if diff < 0 else "#9A6700" if diff > 0 else "#1E6B52"))
            lay.addWidget(big)
        ok, self.movements = run(self, services.shifts.movements, session, int(sh["id"]))
        if not ok:
            self.movements = []
        rows = [["Sales", str(summary.sales_count), m(summary.sales_total)]]
        rows += [[f"   {p['name']}", str(p["n"]), m(p["amount"])] for p in summary.payments]
        rows.append(["Starting cash", "", m(sh["opening_float"])])
        rows.append(["Cash sales", "", m(summary.cash_sales)])
        for mv in self.movements:
            sign = "+" if mv["kind"] in ("cash_in", "expense_void") else "−"
            rows.append([f"{sign} {mv['label']}: {mv['reason'] or ''}", "", m(mv["amount"])])
        if summary.expected_cash is not None:
            rows.append(["Expected cash in drawer", "", m(summary.expected_cash)])
        if sh["counted_cash"] is not None:
            rows.append(["Counted cash", "", m(sh["counted_cash"])])
            rows.append(["Difference (+ over / − short)", "", m(sh["difference"])])
        t = make_table(["", "Count", "Amount"], stretch=0)
        fill_table(t, rows, {1, 2})
        lay.addWidget(t, 1)
        if sh["close_note"]:
            lay.addWidget(label(f"Note: {sh['close_note']}", "Muted", wrap=True))
        lay.addLayout(button_row(button("Print report", self.print_report),
                                 button("Close", self.accept, "Primary")))

    def report(self):
        from services.receipt_service import build_shift_report
        return build_shift_report(self.summary, self.movements, self.services.settings.get())

    def print_report(self) -> bool:
        from ui.dialogs.receipt_dialogs import ReceiptPreviewDialog
        from ui.printing import print_receipt

        def send() -> bool:
            try:
                print_receipt(self.report(), self.services.settings.get().receipt_printer)
                return True
            except Exception as exc:  # noqa: BLE001
                show_error(self, exc)
                return False
        ReceiptPreviewDialog(self.report(), self, on_print=send).exec()
        return True


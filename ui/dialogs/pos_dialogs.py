"""Dialogs used at the checkout."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from models.cart import Discount
from models.product import Product
from models.user import Session
from services.container import Services
from services.sale_service import PaymentInput, PaymentMethod, SaleResult
from ui.dialogs.account_dialogs import _FormDialog
from ui.widgets.common import button, button_row, error_message, label, password_field
from ui.widgets.inputs import MoneyEdit, QuantityEdit
from utils.money import ZERO, format_money, to_money


# --------------------------------------------------------------- approval
class ApprovalDialog(_FormDialog):
    """A manager types their own login to allow something."""

    def __init__(self, services: Services, session: Session, permission: str, action: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent, "Manager approval needed",
                         f"{action}\n\nA manager (or administrator) must enter their own "
                         "username and password to allow this.", "Approve")
        self.services, self.session, self.permission, self.action = services, session, permission, action
        self.approver: Session | None = None
        self.username = QLineEdit()
        self.password = password_field()
        self.form.addRow("Manager username", self.username)
        self.form.addRow("Password", self.password)
        self.username.returnPressed.connect(self.password.setFocus)
        self.username.setFocus()

    def submit(self) -> None:
        try:
            self.approver = self.services.auth.approve(self.username.text(), self.password.text(),
                                                       self.permission, self.action, self.session)
        finally:
            self.password.clear()


def authorize(parent: QWidget, services: Services, session: Session, permission: str,
              action: str) -> Session | None:
    """The current user if allowed, otherwise ask for a manager. None = not approved."""
    if session.can(permission):
        return session
    dlg = ApprovalDialog(services, session, permission, action, parent)
    return dlg.approver if dlg.exec() else None


# --------------------------------------------------------------- discount
DISCOUNT_REASONS = ["Senior citizen", "PWD", "Promo", "Damaged item", "Loyal customer",
                    "Price match", "Other"]


class DiscountDialog(_FormDialog):
    def __init__(self, title: str, base: Decimal, symbol: str, current: Discount | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent, title, f"Applies to {format_money(base, symbol)}.", "Apply discount")
        self.base, self.symbol = base, symbol
        self.discount: Discount | None = None
        self.percent = QRadioButton("Percent (%)")
        self.amount = QRadioButton(f"Amount ({symbol})")
        grp = QButtonGroup(self)
        grp.addButton(self.percent)
        grp.addButton(self.amount)
        self.percent.setChecked(not current or current.kind == "percent")
        self.amount.setChecked(bool(current and current.kind == "amount"))
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.percent)
        rl.addWidget(self.amount)
        rl.addStretch()
        self.value = MoneyEdit("0")
        if current:
            self.value.setText(f"{current.value.normalize():f}")
        self.reason = QComboBox()
        self.reason.setEditable(True)
        self.reason.addItems(DISCOUNT_REASONS)
        if current:
            self.reason.setCurrentText(current.reason)
        self.preview = label("", "SectionTitle")
        self.form.addRow("Type", row)
        self.form.addRow("Discount", self.value)
        self.form.addRow("Reason", self.reason)
        self.form.addRow(self.preview)
        for sig in (self.value.textChanged, self.percent.toggled):
            sig.connect(self._update)
        self._update()
        self.value.setFocus()
        self.value.selectAll()

    def _build(self) -> Discount:
        return Discount("percent" if self.percent.isChecked() else "amount",
                        self.value.text() or "0", self.reason.currentText())

    def _update(self) -> None:
        try:
            d = self._build()
            amt = d.amount_on(self.base)
            self.preview.setText(f"Discount {format_money(amt, self.symbol)}  →  "
                                 f"pay {format_money(self.base - amt, self.symbol)}")
        except Exception:  # noqa: BLE001 - incomplete input while typing
            self.preview.setText("")

    def submit(self) -> None:
        self.discount = self._build()


# --------------------------------------------------------------- quantity
class QuantityDialog(_FormDialog):
    def __init__(self, name: str, current: Decimal, allow_decimal: bool,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent, "Change quantity", name, "OK")
        self.allow_decimal = allow_decimal
        self.field = QuantityEdit()
        self.field.setText(f"{current.normalize():f}")
        self.form.addRow("Quantity" + ("" if allow_decimal else " (whole number)"), self.field)
        self.value: str | None = None
        self.field.setFocus()
        self.field.selectAll()

    def submit(self) -> None:
        from models.cart import parse_quantity
        self.value = str(parse_quantity(self.field.text() or "0", self.allow_decimal))


# --------------------------------------------------------------- product picker
class ProductPickerDialog(QDialog):
    """Several products match the typed text: pick one with arrows + Enter."""

    def __init__(self, products: list[Product], symbol: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose a product")
        self.resize(720, 460)
        self.products = products
        self.chosen: Product | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.addWidget(label(f"{len(products)} products match. Use ↑ ↓ and press Enter.", "SectionTitle"))
        self.table = QTableWidget(len(products), 4)
        self.table.setHorizontalHeaderLabels(["Product", "Barcode", "Unit", "Price"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for r, p in enumerate(products):
            for c, v in enumerate([p.name, p.barcode or "", p.unit_code,
                                   format_money(p.selling_price, symbol)]):
                item = QTableWidgetItem(v)
                if c == 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        self.table.selectRow(0)
        self.table.doubleClicked.connect(lambda _: self.pick())
        lay.addWidget(self.table, 1)
        lay.addLayout(button_row(button("Cancel", self.reject), button("Add to sale", self.pick, "Primary")))
        QShortcut(QKeySequence(Qt.Key_Return), self, activated=self.pick)
        QShortcut(QKeySequence(Qt.Key_Enter), self, activated=self.pick)
        self.table.setFocus()

    def pick(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self.chosen = self.products[rows[0].row()]
            self.accept()


# --------------------------------------------------------------- payment
class PaymentDialog(QDialog):
    """Take payment. Single method: type the amount, press Enter.
    Split: 'Add another payment' keeps the current one and asks for the rest."""

    QUICK = ["20", "50", "100", "200", "500", "1000"]

    def __init__(self, services: Services, session: Session, cart, symbol: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Payment")
        self.setMinimumWidth(640)
        self.services, self.session, self.cart, self.sym = services, session, cart, symbol
        self.total = cart.totals().total
        self.methods: list[PaymentMethod] = services.sales.payment_methods(session)
        self.entries: list[PaymentInput] = []
        self.result: SaleResult | None = None
        self._busy = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)
        lay.addWidget(label("Amount due", "Muted"))
        self.due = QLabel(format_money(self.total, symbol))
        self.due.setStyleSheet("font-size: 30pt; font-weight: 700;")
        lay.addWidget(self.due)
        self.split_info = label("", "Muted", wrap=True)
        lay.addWidget(self.split_info)

        # method buttons (F1, F2, ...)
        mrow = QHBoxLayout()
        self.method_group = QButtonGroup(self)
        self.method_group.setExclusive(True)
        for i, m in enumerate(self.methods):
            b = QPushButton(f"{m.name}  (F{i + 1})" if i < 8 else m.name, checkable=True)
            b.setMinimumHeight(40)
            b.setProperty("method_id", m.id)
            self.method_group.addButton(b, i)
            mrow.addWidget(b)
            if i < 8:
                QShortcut(QKeySequence(f"F{i + 1}"), self, activated=b.click)
        self.method_group.idClicked.connect(lambda _: self._method_changed())
        lay.addLayout(mrow)

        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        self.amount = MoneyEdit()
        self.amount.setStyleSheet("font-size: 18pt; padding: 8px;")
        self.amount_label = label("Amount received")
        grid.addWidget(self.amount_label, 0, 0)
        grid.addWidget(self.amount, 1, 0)
        self.reference = QLineEdit(placeholderText="Reference / transaction number")
        self.reference.setMaxLength(60)
        self.ref_label = label("Reference number *")
        grid.addWidget(self.ref_label, 0, 1)
        grid.addWidget(self.reference, 1, 1)
        lay.addLayout(grid)

        self.quick_row = QHBoxLayout()
        self.quick_buttons = [button("Exact", self._exact)]
        for q in self.QUICK:
            self.quick_buttons.append(button(f"{symbol}{q}", lambda _=False, v=q: self.amount.setText(v)))
        for b in self.quick_buttons:
            b.setObjectName("Quick")
            b.setFocusPolicy(Qt.NoFocus)
            self.quick_row.addWidget(b)
        lay.addLayout(self.quick_row)

        self.change = QLabel("")
        self.change.setStyleSheet("font-size: 20pt; font-weight: 700;")
        lay.addWidget(self.change)
        self.error = label("", "ErrorBox", wrap=True)
        self.error.hide()
        lay.addWidget(self.error)

        self.split_btn = button("Add another payment", self._add_split)
        self.split_btn.setToolTip("Customer pays part with one method and the rest with another")
        self.pay_btn = button("Complete sale  (Enter)", self._complete, "Primary")
        self.pay_btn.setMinimumHeight(46)
        lay.addLayout(button_row(button("Back  (Esc)", self.reject), self.split_btn, self.pay_btn))

        self.amount.textChanged.connect(self._update)
        self.amount.returnPressed.connect(self._complete)
        self.reference.returnPressed.connect(self._complete)
        if self.method_group.buttons():
            self.method_group.button(0).setChecked(True)
        self._method_changed()

    # ------------------------------------------------------------ helpers
    def _method(self) -> PaymentMethod | None:
        i = self.method_group.checkedId()
        return self.methods[i] if 0 <= i < len(self.methods) else None

    def _paid_so_far(self) -> Decimal:
        return sum((to_money(e.tendered) for e in self.entries), ZERO)

    def _remaining(self) -> Decimal:
        return max(ZERO, self.total - self._paid_so_far())

    def _exact(self) -> None:
        self.amount.setText(f"{self._remaining():.2f}")

    def _method_changed(self) -> None:
        m = self._method()
        is_cash = bool(m and m.is_cash)
        needs_ref = bool(m and m.requires_reference)
        for b in self.quick_buttons[1:]:
            b.setVisible(is_cash)
        self.reference.setVisible(needs_ref)
        self.ref_label.setVisible(needs_ref)
        self.amount_label.setText("Cash received" if is_cash else "Amount paid")
        if not is_cash or not self.amount.text():
            self._exact()
        self.amount.setFocus()
        self.amount.selectAll()
        self._update()

    def _amount(self) -> Decimal | None:
        try:
            return to_money(self.amount.text()) if self.amount.text() else None
        except Exception:  # noqa: BLE001
            return None

    def _update(self) -> None:
        self.error.hide()
        rem = self._remaining()
        if self.entries:
            parts = ", ".join(f"{self._name(e.method_id)} {format_money(e.tendered, self.sym)}"
                              for e in self.entries)
            self.split_info.setText(f"Already received: {parts}.  Still due: "
                                    f"{format_money(rem, self.sym)}")
        else:
            self.split_info.setText("")
        amt = self._amount()
        if amt is None:
            self.change.setText("")
        elif amt >= rem:
            self.change.setText(f"Change:  {format_money(amt - rem, self.sym)}")
            self.change.setStyleSheet("font-size: 20pt; font-weight: 700; color: #1E6B52;")
        else:
            self.change.setText(f"Still due:  {format_money(rem - amt, self.sym)}")
            self.change.setStyleSheet("font-size: 20pt; font-weight: 700; color: #9A6700;")

    def _name(self, method_id: int) -> str:
        return next((m.name for m in self.methods if m.id == method_id), "?")

    def _fail(self, exc) -> None:
        self.error.setText(exc if isinstance(exc, str) else error_message(exc)[1])
        self.error.show()

    def _current_entry(self) -> PaymentInput | None:
        m, amt = self._method(), self._amount()
        if m is None or amt is None or amt <= 0:
            return None
        return PaymentInput(m.id, amt, self.reference.text())

    def _add_split(self) -> None:
        entry = self._current_entry()
        if entry is None:
            self._fail("Enter the amount for this payment first.")
            return
        if to_money(entry.tendered) >= self._remaining():
            self._fail("This payment already covers the full amount. Press Complete sale.")
            return
        m = self._method()
        if m.requires_reference and not entry.reference.strip():
            self._fail(f"Enter the reference number for the {m.name} payment.")
            return
        self.entries.append(entry)
        self.reference.clear()
        self.amount.clear()
        self._exact()
        self._update()

    def _complete(self) -> None:
        if self._busy:          # ignore Enter pressed twice
            return
        entry = self._current_entry()
        payments = self.entries + ([entry] if entry else [])
        if self.total > 0 and not payments:
            self._fail("Enter the amount received.")
            return
        self._busy = True
        self.pay_btn.setEnabled(False)
        try:
            self.result = self.services.sales.complete_sale(self.session, self.cart, payments)
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)
            return
        finally:
            self._busy = False
            self.pay_btn.setEnabled(True)
        self.accept()


class SaleCompleteDialog(QDialog):
    def __init__(self, result: SaleResult, symbol: str, parent: QWidget | None = None,
                 on_print=None, printed: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sale complete")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(8)
        lay.addWidget(label(f"✔  Sale {result.sale_no} saved", "StatusOk"))
        lay.addWidget(label(f"Total {format_money(result.total, symbol)}   ·   "
                            f"Received {format_money(result.amount_paid, symbol)}", "Muted"))
        lay.addSpacing(8)
        lay.addWidget(label("Change", "Muted"))
        ch = QLabel(format_money(result.change, symbol))
        ch.setStyleSheet("font-size: 40pt; font-weight: 700; color: #1E6B52;")
        lay.addWidget(ch)
        lay.addSpacing(8)
        buttons = []
        if printed:
            lay.addWidget(label("Receipt printed.", "Muted"))
        if on_print:
            text = "Print another copy  (P)" if printed else "Print receipt  (P)"
            buttons.append(button(text, lambda: on_print(result), None, "P"))
        nxt = button("Next customer  (Enter)", self.accept, "Primary")
        nxt.setDefault(True)
        nxt.setMinimumHeight(42)
        buttons.append(nxt)
        lay.addLayout(button_row(*buttons))
        nxt.setFocus()


class HeldSalesDialog(QDialog):
    def __init__(self, rows: list[dict], symbol: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Held sales")
        self.resize(640, 380)
        self.rows = rows
        self.chosen_id: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.addWidget(label("Choose a held sale to continue", "SectionTitle"))
        self.table = QTableWidget(len(rows), 4)
        self.table.setHorizontalHeaderLabels(["Name", "Held at", "By", "Total"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for r, h in enumerate(rows):
            for c, v in enumerate([h["label"], h["created_at"].strftime("%H:%M"), h["held_by"],
                                   format_money(h["total"], symbol)]):
                self.table.setItem(r, c, QTableWidgetItem(v))
        if rows:
            self.table.selectRow(0)
        self.table.doubleClicked.connect(lambda _: self.pick())
        lay.addWidget(self.table, 1)
        lay.addLayout(button_row(button("Cancel", self.reject), button("Continue this sale", self.pick, "Primary")))
        QShortcut(QKeySequence(Qt.Key_Return), self, activated=self.pick)
        self.table.setFocus()

    def pick(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self.chosen_id = int(self.rows[rows[0].row()]["id"])
            self.accept()


def parse_scan(text: str) -> tuple[str, str]:
    """'3*4801981116072' -> ('3', '4801981116072'); plain code -> ('1', code)."""
    text = text.strip()
    if "*" in text:
        qty, _, code = text.partition("*")
        qty = qty.strip()
        try:
            if qty and Decimal(qty) > 0:
                return qty, code.strip()
        except InvalidOperation:
            pass
    return "1", text

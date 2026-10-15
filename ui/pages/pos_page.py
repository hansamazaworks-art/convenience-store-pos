"""Checkout screen - built for a barcode scanner and the keyboard.

Keys:  scan / type + Enter = add item     3*code = add 3
       ↑ ↓ select item   + / - quantity   F4 quantity   Del remove item
       F6 item discount   F7 sale discount   F8 hold   F9 recall
       F10 cancel sale    F12 or Space (empty box) = pay
"""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from models.cart import Cart, parse_quantity
from ui.dialogs.pos_dialogs import (
    DiscountDialog, HeldSalesDialog, PaymentDialog, ProductPickerDialog, QuantityDialog,
    SaleCompleteDialog, authorize, parse_scan,
)
from ui.dialogs.receipt_dialogs import print_sale_receipt
from ui.pages.base import Page
from ui.widgets.common import button, confirm, error_message, label, run
from utils.money import format_money

_COLS = ["#", "Item", "Qty", "Price", "Discount", "Total"]


class PosPage(Page):
    title = "Checkout"

    def __init__(self, services, session) -> None:
        super().__init__(services, session)
        self.cart = Cart()
        self.symbol = "₱"
        self.block_no_stock = False
        self.lay.setContentsMargins(20, 16, 20, 16)
        self.lay.itemAt(0).widget().hide()  # no big page title: space is for the sale

        body = QHBoxLayout()
        body.setSpacing(16)
        self.lay.addLayout(body, 1)

        # ------------------------------------------------ left: scan + cart
        left = QVBoxLayout()
        left.setSpacing(10)
        self.scan = QLineEdit(placeholderText="Scan barcode or type product name, then Enter")
        self.scan.setStyleSheet("font-size: 15pt; padding: 10px 12px;")
        self.scan.returnPressed.connect(self.on_scan)
        self.scan.installEventFilter(self)
        left.addWidget(self.scan)
        self.shift_banner = QFrame(objectName="Card")
        bl = QHBoxLayout(self.shift_banner)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.addWidget(label("Your shift is not open. Count the starting cash and open your shift "
                           "before selling.", "SectionTitle", wrap=True), 1)
        bl.addWidget(button("Open shift…", self.open_shift, "Primary"))
        self.shift_banner.hide()
        left.addWidget(self.shift_banner)
        self.message = label("", wrap=True)
        self.message.hide()
        left.addWidget(self.message)

        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)  # the scan box keeps the keyboard
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setStyleSheet("font-size: 12pt;")
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for i in range(len(_COLS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda _: self.change_quantity())
        left.addWidget(self.table, 1)
        left.addWidget(label("Enter add  ·  3*code add 3  ·  ↑↓ select  ·  + / − qty  ·  "
                             "F4 qty  ·  Del remove  ·  F6 item disc.  ·  F7 sale disc.  ·  "
                             "F8 hold  ·  F9 recall  ·  F10 cancel  ·  F12 pay", "Muted", wrap=True))
        body.addLayout(left, 1)

        # ------------------------------------------------ right: totals + actions
        right_w = QWidget()
        right_w.setFixedWidth(360)
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        totals = QFrame(objectName="Card")
        tl = QGridLayout(totals)
        tl.setContentsMargins(20, 16, 20, 16)
        tl.setVerticalSpacing(6)
        self.lbl_items = QLabel()
        self.lbl_sub = QLabel()
        self.lbl_disc = QLabel()
        for r, (cap, w) in enumerate([("Items", self.lbl_items), ("Subtotal", self.lbl_sub),
                                      ("Discount", self.lbl_disc)]):
            tl.addWidget(label(cap, "Muted"), r, 0)
            w.setAlignment(Qt.AlignRight)
            tl.addWidget(w, r, 1)
        tl.addWidget(label("TOTAL", "SectionTitle"), 3, 0, 1, 2)
        self.lbl_total = QLabel()
        self.lbl_total.setAlignment(Qt.AlignRight)
        self.lbl_total.setStyleSheet("font-size: 34pt; font-weight: 700; color: #123A2E;")
        tl.addWidget(self.lbl_total, 4, 0, 1, 2)
        self.lbl_sale_disc = label("", "Muted", wrap=True)
        tl.addWidget(self.lbl_sale_disc, 5, 0, 1, 2)
        right.addWidget(totals)

        self.pay_btn = button("PAY  (F12)", self.pay, "Primary")
        self.pay_btn.setMinimumHeight(64)
        self.pay_btn.setStyleSheet("font-size: 18pt;")
        right.addWidget(self.pay_btn)

        grid = QGridLayout()
        grid.setSpacing(8)
        self.btn_qty = button("Quantity  F4", self.change_quantity)
        self.btn_remove = button("Remove item  Del", self.remove_line)
        self.btn_line_disc = button("Item discount  F6", self.line_discount)
        self.btn_sale_disc = button("Sale discount  F7", self.sale_discount)
        self.btn_hold = button("Hold  F8", self.hold)
        self.btn_recall = button("Recall  F9", self.recall)
        self.btn_cancel = button("Cancel sale  F10", self.cancel_sale, "Danger")
        for i, b in enumerate([self.btn_qty, self.btn_remove, self.btn_line_disc, self.btn_sale_disc,
                               self.btn_hold, self.btn_recall]):
            b.setMinimumHeight(44)
            b.setFocusPolicy(Qt.NoFocus)
            grid.addWidget(b, i // 2, i % 2)
        self.btn_cancel.setMinimumHeight(44)
        self.btn_cancel.setFocusPolicy(Qt.NoFocus)
        self.pay_btn.setFocusPolicy(Qt.NoFocus)
        grid.addWidget(self.btn_cancel, 3, 0, 1, 2)
        right.addLayout(grid)
        right.addStretch()
        self.cashier_label = label(f"Cashier: {session.full_name}", "Muted")
        right.addWidget(self.cashier_label)
        body.addWidget(right_w)

        for key, fn in [("F4", self.change_quantity), ("Delete", self.remove_line),
                        ("F6", self.line_discount), ("F7", self.sale_discount),
                        ("F8", self.hold), ("F9", self.recall), ("F10", self.cancel_sale),
                        ("F12", self.pay), ("F2", self.focus_scan)]:
            QShortcut(QKeySequence(key), self, activated=fn, context=Qt.WidgetWithChildrenShortcut)
        self.render()

    # ------------------------------------------------------------- plumbing
    @property
    def has_open_sale(self) -> bool:
        return not self.cart.is_empty

    def on_show(self) -> None:
        ok, s = run(self, self.services.settings.get)
        if ok:
            self.symbol = s.currency_symbol
            self.block_no_stock = not s.allow_negative_stock
        self._check_shift()
        self.render()
        self.focus_scan()

    def _check_shift(self) -> None:
        """Selling needs an open shift (unless the store switched that off)."""
        ok, required = run(self, self.services.shifts.required)
        ok2, shift = run(self, self.services.shifts.current, self.session)
        blocked = bool(ok and required and ok2 and shift is None)
        self.shift_banner.setVisible(blocked)
        self.scan.setEnabled(not blocked)

    def open_shift(self) -> None:
        from ui.dialogs.shift_dialogs import OpenShiftDialog
        if OpenShiftDialog(self.services, self.session, self).exec():
            self._check_shift()
            self.say("Shift opened. You can start selling.")
        self.focus_scan()

    def focus_scan(self) -> None:
        self.scan.setFocus()

    def eventFilter(self, obj, event):  # noqa: N802 - Qt name
        if obj is self.scan and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Up, Qt.Key_Down):
                self._move_selection(-1 if key == Qt.Key_Up else 1)
                return True
            if not self.scan.text():
                if key in (Qt.Key_Plus, Qt.Key_Equal):
                    self.bump_quantity(1)
                    return True
                if key == Qt.Key_Minus:
                    self.bump_quantity(-1)
                    return True
                if key == Qt.Key_Space:
                    self.pay()
                    return True
        return super().eventFilter(obj, event)

    def _move_selection(self, step: int) -> None:
        n = len(self.cart.lines)
        if n:
            self.table.selectRow(max(0, min(n - 1, self.selected_index() + step)))

    def selected_index(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else len(self.cart.lines) - 1

    def say(self, text: str, error: bool = False) -> None:
        self.message.setObjectName("ErrorBox" if error else "Muted")
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def _do(self, fn, *args):
        """Run a cart change; show problems in the message line (not a pop-up)."""
        try:
            return True, fn(*args)
        except Exception as exc:  # noqa: BLE001
            self.say(error_message(exc)[1], error=True)
            return False, None

    # --------------------------------------------------------------- render
    def render(self, select: int | None = None) -> None:
        sym = self.symbol
        lines = self.cart.lines
        self.table.setRowCount(len(lines))
        right = Qt.AlignRight | Qt.AlignVCenter
        for r, l in enumerate(lines):
            disc = ""
            if l.discount:
                disc = f"-{format_money(l.discount_amount, sym)}"
            vals = [(str(r + 1), None), (l.name, None),
                    (f"{l.quantity.normalize():f} {l.unit_code}", right),
                    (format_money(l.unit_price, sym), right), (disc, right),
                    (format_money(l.net, sym), right)]
            for c, (v, align) in enumerate(vals):
                item = QTableWidgetItem(v)
                if align:
                    item.setTextAlignment(align)
                if c == 4 and l.discount:
                    item.setToolTip(f"{l.discount.reason}" +
                                    (f" (approved by {l.discount.approved_by_name})"
                                     if l.discount.approved_by_name else ""))
                self.table.setItem(r, c, item)
        if lines:
            self.table.selectRow(len(lines) - 1 if select is None else select)
        t = self.cart.totals()
        self.lbl_items.setText(f"{t.item_count.normalize():f}")
        self.lbl_sub.setText(format_money(t.subtotal, sym))
        self.lbl_disc.setText(f"-{format_money(t.discount_total, sym)}" if t.discount_total else "—")
        self.lbl_total.setText(format_money(t.total, sym))
        sd = self.cart.sale_discount
        self.lbl_sale_disc.setText(f"Sale discount {sd.label(sym)} — {sd.reason}" if sd else "")
        has = bool(lines)
        for b in (self.pay_btn, self.btn_qty, self.btn_remove, self.btn_line_disc,
                  self.btn_sale_disc, self.btn_hold, self.btn_cancel):
            b.setEnabled(has)
        ok, n = run(self, self.services.sales.held_count, self.session)
        self.btn_recall.setText(f"Recall  F9  ({n})" if ok and n else "Recall  F9")
        self.btn_recall.setEnabled(bool(ok and n) and not has)

    # ---------------------------------------------------------------- items
    def on_scan(self) -> None:
        text = self.scan.text().strip()
        if not text:
            return
        qty, code = parse_scan(text)
        if not code:
            return
        ok, product = run(self, self.services.products.find_by_code, self.session, code)
        if not ok:
            return
        if product is None:
            ok, matches = run(self, self.services.products.search, self.session, code, None, False, 50)
            if not ok:
                return
            if not matches:
                self.say(f"No product found for '{code}'.", error=True)
                self.scan.selectAll()
                return
            if len(matches) == 1:
                product = matches[0]
            else:
                dlg = ProductPickerDialog(matches, self.symbol, self)
                if not dlg.exec() or dlg.chosen is None:
                    self.focus_scan()
                    return
                product = dlg.chosen
        if not product.is_active:
            self.say(f"'{product.name}' is deactivated and cannot be sold.", error=True)
            return
        ok, add_qty = self._do(parse_quantity, qty, product.unit_allow_decimal)
        if not ok or not self._stock_ok(product.id, product.name, self._in_cart(product.id) + add_qty):
            self.scan.selectAll()
            return
        ok, index = self._do(self.cart.add, product, qty)
        if ok:
            self.scan.clear()
            self.say(f"Added {product.name}")
            self.render(index)
        self.focus_scan()

    def bump_quantity(self, step: int) -> None:
        if self.cart.is_empty:
            return
        i = self.selected_index()
        line = self.cart.lines[i]
        new = line.quantity + step
        if new <= 0:
            self.remove_line()
            return
        self._set_quantity(i, new)

    def change_quantity(self) -> None:
        if self.cart.is_empty:
            return
        i = self.selected_index()
        line = self.cart.lines[i]
        dlg = QuantityDialog(line.name, line.quantity, line.allow_decimal, self)
        if dlg.exec() and dlg.value:
            self._set_quantity(i, Decimal(dlg.value))
        self.focus_scan()

    def _in_cart(self, product_id: int) -> Decimal:
        return sum((l.quantity for l in self.cart.lines if l.product_id == product_id), Decimal(0))

    def _stock_ok(self, product_id: int, name: str, wanted: Decimal) -> bool:
        """When the store blocks selling without stock, stop here instead of at payment."""
        if not self.block_no_stock:
            return True
        ok, have = run(self, self.services.inventory.available, self.session, product_id)
        if not ok:
            return False
        if wanted > have:
            self.say(f"Not enough stock for '{name}': {have.normalize():f} in stock. "
                     "If the shelf has more, ask someone to record it in Inventory.", error=True)
            return False
        return True

    def _set_quantity(self, i: int, new: Decimal) -> None:
        line = self.cart.lines[i]
        old = line.quantity
        if new > old and not self._stock_ok(line.product_id, line.name,
                                            self._in_cart(line.product_id) - old + new):
            return
        if new < old:
            approver = authorize(self, self.services, self.session, "pos.void_line",
                                 f"Reduce '{line.name}' from {old.normalize():f} to {new.normalize():f}.")
            if approver is None:
                self.focus_scan()
                return
        ok, _ = self._do(self.cart.set_quantity, i, new)
        if ok:
            if new < old:
                self.services.sales.record_void(
                    self.session, "line", {"item": line.name, "from": old, "to": new},
                    approver if approver is not self.session else None)
            self.say("")
            self.render(i)

    def remove_line(self) -> None:
        if self.cart.is_empty:
            return
        i = self.selected_index()
        line = self.cart.lines[i]
        approver = authorize(self, self.services, self.session, "pos.void_line",
                             f"Remove '{line.name}' ({line.quantity.normalize():f}) from the sale.")
        if approver is None:
            self.focus_scan()
            return
        removed = self.cart.remove(i)
        self.services.sales.record_void(
            self.session, "line", {"item": removed.name, "qty": removed.quantity,
                                   "amount": removed.net},
            approver if approver is not self.session else None)
        self.say(f"Removed {removed.name}")
        self.render(min(i, len(self.cart.lines) - 1) if self.cart.lines else None)
        self.focus_scan()

    # ------------------------------------------------------------ discounts
    def line_discount(self) -> None:
        if self.cart.is_empty:
            return
        i = self.selected_index()
        line = self.cart.lines[i]
        dlg = DiscountDialog(f"Discount on {line.name}", line.gross, self.symbol, line.discount, self)
        if not dlg.exec():
            self.focus_scan()
            return
        approver = authorize(self, self.services, self.session, "pos.discount",
                             f"Discount on '{line.name}': {dlg.discount.label(self.symbol)} "
                             f"({dlg.discount.reason}).")
        if approver:
            d = dlg.discount
            d.approved_by, d.approved_by_name = approver.user_id, approver.full_name
            self.cart.set_line_discount(i, d)
            self.render(i)
        self.focus_scan()

    def sale_discount(self) -> None:
        if self.cart.is_empty:
            return
        t = self.cart.totals()
        base = t.subtotal - t.line_discount
        dlg = DiscountDialog("Discount on the whole sale", base, self.symbol, self.cart.sale_discount, self)
        if not dlg.exec():
            self.focus_scan()
            return
        approver = authorize(self, self.services, self.session, "pos.discount",
                             f"Discount on the whole sale: {dlg.discount.label(self.symbol)} "
                             f"({dlg.discount.reason}).")
        if approver:
            d = dlg.discount
            d.approved_by, d.approved_by_name = approver.user_id, approver.full_name
            self._do(self.cart.set_sale_discount, d)
            self.render(self.selected_index())
        self.focus_scan()

    # ------------------------------------------------------- hold / cancel
    def hold(self) -> None:
        if self.cart.is_empty:
            return
        name, ok = QInputDialog.getText(self, "Hold sale",
                                        "A name to find it again (e.g. 'man in blue shirt'):")
        if not ok:
            self.focus_scan()
            return
        ok, _ = run(self, self.services.sales.hold, self.session, self.cart, name)
        if ok:
            self.cart = Cart()
            self.say("Sale put on hold. Press F9 to continue it later.")
            self.render()
        self.focus_scan()

    def recall(self) -> None:
        if not self.cart.is_empty:
            self.say("Finish or hold the current sale before recalling another.", error=True)
            return
        ok, rows = run(self, self.services.sales.held_sales, self.session)
        if not ok or not rows:
            self.say("There are no held sales.")
            return
        dlg = HeldSalesDialog(rows, self.symbol, self)
        if dlg.exec() and dlg.chosen_id:
            ok, cart = run(self, self.services.sales.recall, self.session, dlg.chosen_id)
            if ok:
                self.cart = cart
                self.say("Held sale recalled.")
                self.render()
        self.focus_scan()

    def cancel_sale(self) -> None:
        if self.cart.is_empty:
            return
        t = self.cart.totals()
        if not confirm(self, "Cancel sale", f"Cancel this sale of {format_money(t.total, self.symbol)}?\n"
                       "All items will be removed.", "Cancel sale"):
            self.focus_scan()
            return
        approver = authorize(self, self.services, self.session, "pos.void_sale",
                             f"Cancel a sale of {format_money(t.total, self.symbol)}.")
        if approver is None:
            self.focus_scan()
            return
        self.services.sales.record_void(
            self.session, "sale", {"items": len(self.cart.lines), "total": t.total},
            approver if approver is not self.session else None)
        self.cart = Cart()
        self.say("Sale cancelled.")
        self.render()
        self.focus_scan()

    # ----------------------------------------------------------------- pay
    def pay(self) -> None:
        if self.cart.is_empty:
            return
        dlg = PaymentDialog(self.services, self.session, self.cart, self.symbol, parent=self)
        if dlg.exec() and dlg.result:
            result = dlg.result
            self.cart = Cart()
            self.say(f"Sale {result.sale_no} saved." +
                     (" (It had already been saved - no duplicate was made.)" if result.already_saved else ""))
            self.render()
            store = self.services.settings.get()
            printed = False
            if store.receipt_auto_print and store.receipt_printer and not result.already_saved:
                printed = print_sale_receipt(self, self.services, self.session, result.sale_id)
            SaleCompleteDialog(result, self.symbol, self, printed=printed,
                               on_print=lambda r: print_sale_receipt(self, self.services,
                                                                     self.session, r.sale_id)).exec()
        self.focus_scan()

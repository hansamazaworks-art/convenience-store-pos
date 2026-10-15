"""Store settings (administrators)."""
from __future__ import annotations

from dataclasses import replace
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLineEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ui.dialogs.account_dialogs import _FormDialog
from ui.pages.base import Page
from services.receipt_service import sample_receipt
from ui.widgets.common import button, button_row, card, info, label, run


class PaymentMethodDialog(_FormDialog):
    def __init__(self, services, session, method=None, parent=None) -> None:
        super().__init__(parent, "Edit payment method" if method else "Add payment method",
                         "Non-cash ways customers can pay, e.g. GCash, Maya, Card, Bank transfer.",
                         "Save")
        self.services, self.session, self.method = services, session, method
        self.name = QLineEdit(method.name if method else "")
        self.name.setMaxLength(40)
        self.ref = QCheckBox("Cashier must type a reference / transaction number")
        self.ref.setChecked(method.requires_reference if method else True)
        self.form.addRow("Name", self.name)
        if not (method and method.is_cash):
            self.form.addRow(self.ref)

    def submit(self) -> None:
        m = self.method
        self.services.sales.save_payment_method(self.session, self.name.text(), self.ref.isChecked(),
                                                m.id if m else None, m.is_active if m else True)

_COSTING = {"WEIGHTED_AVERAGE": "Weighted average cost (recalculated each time stock is received)"}


class SettingsPage(Page):
    title = "Store settings"
    subtitle = "These details appear on receipts and reports."

    def __init__(self, services, session, on_saved: Callable[[], None] | None = None) -> None:
        super().__init__(services, session)
        self.on_saved = on_saved
        box, lay = card()
        box.setMaximumWidth(720)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(16)
        self.fields: dict[str, QLineEdit] = {}
        for key, caption, maxlen, hint in [
            ("store_name", "Store name", 100, "Shown on the login screen and receipts"),
            ("store_address", "Address", 200, "Printed on receipts"),
            ("store_phone", "Phone", 50, ""),
            ("tax_id", "Tax / business ID", 50, "e.g. TIN or business registration number"),
            ("currency_symbol", "Currency symbol", 5, "e.g. ₱  or  S$"),
            ("receipt_footer", "Receipt footer", 200, "e.g. Thank you for shopping!"),
        ]:
            f = QLineEdit()
            f.setMaxLength(maxlen)
            f.setPlaceholderText(hint)
            self.fields[key] = f
            form.addRow(caption, f)
        self.costing = label("", "Muted", wrap=True)
        form.addRow("Inventory costing", self.costing)
        self.allow_negative = QCheckBox("Allow selling items the system shows as out of stock")
        self.allow_negative.setToolTip(
            "Leave this OFF once your stock is entered: the checkout then refuses to sell more "
            "than is in stock, so stock numbers stay correct.")
        form.addRow("Stock", self.allow_negative)
        lay.addLayout(form)

        # ---- receipt printer
        pr_box, pr = card()
        pr.addWidget(label("Receipt printer", "SectionTitle"))
        pform = QFormLayout()
        pform.setVerticalSpacing(10)
        pform.setHorizontalSpacing(16)
        self.printer = QComboBox()
        self.printer.setMinimumWidth(260)
        self.width_mm = QComboBox()
        self.width_mm.addItem("58 mm (small)", "58")
        self.width_mm.addItem("80 mm (wide)", "80")
        self.auto_print = QCheckBox("Print the receipt automatically after each sale")
        self.receipt_note = QLineEdit()
        self.receipt_note.setMaxLength(200)
        self.receipt_note.setPlaceholderText("Optional, e.g. 'Goods sold are not returnable after 7 days'")
        pform.addRow("Printer", self.printer)
        pform.addRow("Paper width", self.width_mm)
        pform.addRow("", self.auto_print)
        pform.addRow("Receipt note", self.receipt_note)
        pr.addLayout(pform)
        pr.addLayout(button_row(button("Preview test receipt", self.preview_test),
                                button("Print test receipt", self.print_test), stretch_first=False))

        self.save_btn = button("Save settings", self.save, "Primary", "Ctrl+S")
        self.revert_btn = button("Undo changes", self.on_show)
        left_col = QVBoxLayout()
        left_col.setSpacing(16)
        left_col.addWidget(box)
        left_col.addWidget(pr_box)
        left_col.addLayout(button_row(self.revert_btn, self.save_btn))
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addLayout(left_col, 3)

        pm_box, pm = card()
        pm.addWidget(label("Payment methods", "SectionTitle"))
        self.pm_table = QTableWidget(0, 3)
        self.pm_table.setHorizontalHeaderLabels(["Method", "Needs reference", "Status"])
        self.pm_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pm_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.pm_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pm_table.verticalHeader().hide()
        self.pm_table.verticalHeader().setDefaultSectionSize(32)
        self.pm_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.pm_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.pm_table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.pm_table.itemSelectionChanged.connect(self._pm_buttons)
        self.pm_table.doubleClicked.connect(lambda _: self.edit_method())
        pm.addWidget(self.pm_table, 1)
        self.pm_edit = button("Edit", self.edit_method)
        self.pm_toggle = button("Turn off", self.toggle_method)
        pm.addLayout(button_row(button("+ Add", self.add_method), self.pm_edit, self.pm_toggle,
                                stretch_first=False))
        bk_box, bk = card()
        bk.addWidget(label("Backups", "SectionTitle"))
        self.backup_status = label("", wrap=True)
        bk.addWidget(self.backup_status)
        bk.addWidget(label("A backup is made automatically once a day when the POS starts. Copy the "
                           "backups folder to a USB stick or online storage now and then.", "Muted", wrap=True))
        bk.addLayout(button_row(button("Open backups folder", self.open_backup_folder),
                                button("Back up now", self.backup_now, "Primary"), stretch_first=False))
        right_col = QVBoxLayout()
        right_col.addWidget(pm_box)
        right_col.addWidget(bk_box)
        right_col.addStretch()
        row.addLayout(right_col, 2)
        self.lay.addLayout(row)
        self.lay.addStretch()
        self.methods = []

    # ------------------------------------------------------- payment methods
    def _load_methods(self) -> None:
        ok, methods = run(self, self.services.sales.payment_methods, self.session, True)
        if not ok:
            return
        self.methods = methods
        self.pm_table.setRowCount(len(methods))
        for r, m in enumerate(methods):
            for c, v in enumerate([m.name, "Yes" if m.requires_reference else "No",
                                   "On" if m.is_active else "Off"]):
                item = QTableWidgetItem(v)
                if not m.is_active:
                    item.setForeground(Qt.gray)
                self.pm_table.setItem(r, c, item)
        self._pm_buttons()

    def _selected_method(self):
        rows = self.pm_table.selectionModel().selectedRows()
        return self.methods[rows[0].row()] if rows else None

    def _pm_buttons(self) -> None:
        m = self._selected_method()
        self.pm_edit.setEnabled(m is not None)
        self.pm_toggle.setEnabled(m is not None and not m.is_cash)
        self.pm_toggle.setText("Turn on" if m and not m.is_active else "Turn off")

    def add_method(self) -> None:
        if PaymentMethodDialog(self.services, self.session, parent=self).exec():
            self._load_methods()

    def edit_method(self) -> None:
        m = self._selected_method()
        if m and PaymentMethodDialog(self.services, self.session, m, self).exec():
            self._load_methods()

    def toggle_method(self) -> None:
        m = self._selected_method()
        if m:
            ok, _ = run(self, self.services.sales.save_payment_method, self.session, m.name,
                        m.requires_reference, m.id, not m.is_active)
            if ok:
                self._load_methods()

    # ------------------------------------------------------------- backups
    def _show_backup_status(self) -> None:
        b = self.services.backups
        last = b.last_backup()
        text = (f"Last backup: {last.created:%d %b %Y %H:%M} ({last.size / 1024:,.0f} KB)" if last
                else "No backup has been made yet.")
        if b.last_error:
            text += f"\n⚠ The last automatic backup failed: {b.last_error}"
        self.backup_status.setText(text + f"\nFolder: {b.backup_dir}")

    def backup_now(self) -> None:
        ok, made = run(self, self.services.backups.backup_now, self.session)
        self._show_backup_status()
        if ok:
            info(self, "Backup made", f"Saved as {made.name}")

    def open_backup_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        folder = self.services.backups.backup_dir
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def on_show(self) -> None:
        self._load_methods()
        self._show_backup_status()
        ok, s = run(self, self.services.settings.get)
        if not ok:
            return
        for key, f in self.fields.items():
            f.setText(getattr(s, key))
        self.costing.setText(_COSTING.get(s.costing_method, s.costing_method))
        self._load_printers(s.receipt_printer)
        self.width_mm.setCurrentIndex(1 if s.receipt_width_mm == 80 else 0)
        self.auto_print.setChecked(s.receipt_auto_print)
        self.receipt_note.setText(s.receipt_note)
        self.allow_negative.setChecked(s.allow_negative_stock)

    # ------------------------------------------------------------- printer
    def _load_printers(self, current: str) -> None:
        from ui.printing import available_printers
        self.printer.clear()
        self.printer.addItem("— No receipt printer —", "")
        names = available_printers()
        for n in names:
            self.printer.addItem(n, n)
        if current and current not in names:
            self.printer.addItem(f"{current}  (not found on this PC)", current)
        self.printer.setCurrentIndex(max(0, self.printer.findData(current)))

    def _test_receipt(self):
        values = {k: f.text() for k, f in self.fields.items()}
        store = self.services.settings.get()
        store = replace(store, store_name=values["store_name"] or store.store_name,
                        store_address=values["store_address"], store_phone=values["store_phone"],
                        tax_id=values["tax_id"], receipt_footer=values["receipt_footer"],
                        currency_symbol=values["currency_symbol"] or store.currency_symbol,
                        receipt_note=self.receipt_note.text())
        return sample_receipt(store, int(self.width_mm.currentData()))

    def preview_test(self) -> None:
        from ui.dialogs.receipt_dialogs import ReceiptPreviewDialog
        ReceiptPreviewDialog(self._test_receipt(), self, on_print=self.print_test).exec()

    def print_test(self) -> bool:
        from ui.printing import print_receipt
        name = self.printer.currentData()
        ok, _ = run(self, print_receipt, self._test_receipt(), name)
        if ok:
            info(self, "Test receipt sent",
                 f"A test receipt was sent to '{name}'.\n\nThe row of numbers should fit on one "
                 "line. If it is cut off or very small, change the paper width. Remember to "
                 "click Save settings.")
        return ok

    def save(self) -> None:
        values = {k: f.text() for k, f in self.fields.items()}
        values.update(receipt_printer=self.printer.currentData() or "",
                      receipt_width_mm=self.width_mm.currentData(),
                      receipt_auto_print="1" if self.auto_print.isChecked() else "0",
                      receipt_note=self.receipt_note.text(),
                      allow_negative_stock="1" if self.allow_negative.isChecked() else "0")
        ok, _ = run(self, self.services.settings.update, self.session, values)
        if ok:
            self.on_show()
            info(self, "Saved", "Store settings were saved.")
            if self.on_saved:
                self.on_saved()

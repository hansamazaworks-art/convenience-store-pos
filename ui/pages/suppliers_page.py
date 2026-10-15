"""Suppliers: a simple list (name, phone, note) to pick from when receiving stock."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLineEdit

from ui.dialogs.account_dialogs import _FormDialog
from ui.pages.base import Page
from ui.widgets.common import button, label, run
from ui.widgets.tables import fill_table, make_table, selected_row


class SupplierDialog(_FormDialog):
    def __init__(self, services, session, supplier: dict | None = None, parent=None) -> None:
        super().__init__(parent, "Edit supplier" if supplier else "Add supplier", "", "Save")
        self.services, self.session, self.supplier = services, session, supplier
        self.saved_id = None
        self.name = QLineEdit(supplier["name"] if supplier else "")
        self.name.setMaxLength(100)
        self.phone = QLineEdit((supplier or {}).get("phone") or "")
        self.phone.setMaxLength(50)
        self.note = QLineEdit((supplier or {}).get("note") or "")
        self.note.setMaxLength(200)
        self.note.setPlaceholderText("e.g. delivers every Tuesday")
        self.form.addRow("Name *", self.name)
        self.form.addRow("Phone", self.phone)
        self.form.addRow("Note", self.note)

    def submit(self) -> None:
        s = self.supplier
        self.saved_id = self.services.purchasing.save_supplier(
            self.session, self.name.text(), self.phone.text(), self.note.text(),
            int(s["id"]) if s else None, bool(s["is_active"]) if s else True)


class SuppliersPage(Page):
    title = "Suppliers"
    subtitle = "Who you buy from. Choosing a supplier when receiving stock is optional."

    def __init__(self, services, session) -> None:
        super().__init__(services, session)
        self.rows = []
        self.table = make_table(["Name", "Phone", "Note", "Deliveries", "Last delivery", "Status"],
                                stretch=2)
        self.table.doubleClicked.connect(lambda _: self.edit())
        self.lay.addWidget(self.table, 1)
        foot = QHBoxLayout()
        self.summary = label("", "Muted")
        foot.addWidget(self.summary, 1)
        self.toggle_btn = button("Turn off", self.toggle)
        foot.addWidget(self.toggle_btn)
        foot.addWidget(button("Edit", self.edit))
        foot.addWidget(button("+ Add supplier", self.add, "Primary"))
        self.lay.addLayout(foot)
        self.table.itemSelectionChanged.connect(self._buttons)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        ok, rows = run(self, self.services.purchasing.suppliers, self.session, True)
        if not ok:
            return
        self.rows = rows
        fill_table(self.table, [[r["name"], r["phone"] or "", r["note"] or "", str(r["receipts"]),
                                 r["last_delivery"].strftime("%d %b %Y") if r["last_delivery"] else "",
                                 "Active" if r["is_active"] else "Off"] for r in rows], {3})
        self.summary.setText(f"{len(rows)} supplier{'s' if len(rows) != 1 else ''}")
        self._buttons()

    def _selected(self):
        r = selected_row(self.table)
        return self.rows[r] if r is not None else None

    def _buttons(self) -> None:
        s = self._selected()
        self.toggle_btn.setEnabled(s is not None)
        self.toggle_btn.setText("Turn on" if s and not s["is_active"] else "Turn off")

    def add(self) -> None:
        if SupplierDialog(self.services, self.session, None, self).exec():
            self.refresh()

    def edit(self) -> None:
        s = self._selected()
        if s and SupplierDialog(self.services, self.session, s, self).exec():
            self.refresh()

    def toggle(self) -> None:
        s = self._selected()
        if s:
            ok, _ = run(self, self.services.purchasing.save_supplier, self.session, s["name"],
                        s["phone"] or "", s["note"] or "", int(s["id"]), not s["is_active"])
            if ok:
                self.refresh()

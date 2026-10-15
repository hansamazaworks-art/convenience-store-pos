"""Physical stock counts. Also the way to enter OPENING stock the first time."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit

from ui.dialogs.account_dialogs import _FormDialog
from ui.dialogs.inventory_dialogs import CountSheetDialog
from ui.pages.base import Page
from ui.widgets.common import button, confirm, label, run
from ui.widgets.tables import fill_table, make_table, selected_row

_STATUS = {"draft": "In progress", "posted": "Finished", "cancelled": "Cancelled"}


class NewCountDialog(_FormDialog):
    def __init__(self, services, session, parent=None) -> None:
        super().__init__(parent, "New stock count",
                         "Makes a count sheet with every active product (or one category). "
                         "Count the shelves, type the numbers, then finish the count.", "Start count")
        self.services, self.session = services, session
        self.count_id = None
        self.category = QComboBox()
        self.category.addItem("All products", None)
        ok, cats = run(self, services.catalog.list_items, session, "category", False)
        for c in cats if ok else []:
            self.category.addItem(c.name, c.id)
        self.note = QLineEdit(placeholderText="e.g. 'Opening stock' or 'Month-end count'")
        self.note.setMaxLength(200)
        self.form.addRow("Products", self.category)
        self.form.addRow("Note", self.note)

    def submit(self) -> None:
        self.count_id = self.services.inventory.start_count(self.session, self.note.text(),
                                                            self.category.currentData())


class StockCountPage(Page):
    title = "Stock count"
    subtitle = ("Count what is on the shelves and correct the system. First time: use a count "
                "to enter your opening stock.")

    def __init__(self, services, session) -> None:
        super().__init__(services, session)
        self.rows = []
        self.table = make_table(["Count no.", "Started", "Products", "Note", "Counted", "Status",
                                 "Started by", "Finished by"], stretch=3)
        self.table.doubleClicked.connect(lambda _: self.open_count())
        self.lay.addWidget(self.table, 1)
        foot = QHBoxLayout()
        self.summary = label("", "Muted")
        foot.addWidget(self.summary, 1)
        self.cancel_btn = button("Cancel count", self.cancel_count, "Danger")
        foot.addWidget(self.cancel_btn)
        foot.addWidget(button("Open", self.open_count))
        foot.addWidget(button("+ New count", self.new_count, "Primary"))
        self.lay.addLayout(foot)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        ok, rows = run(self, self.services.inventory.list_counts, self.session)
        if not ok:
            return
        self.rows = rows
        fill_table(self.table, [[r["count_no"], r["created_at"].strftime("%d %b %Y %H:%M"),
                                 r["category_name"] or "All", r["note"] or "",
                                 f"{r['counted']} of {r['line_count']}", _STATUS[r["status"]],
                                 r["created_by_name"], r["posted_by_name"] or ""] for r in rows],
                   {4})
        drafts = sum(1 for r in rows if r["status"] == "draft")
        self.summary.setText(f"{drafts} count{'s' if drafts != 1 else ''} in progress." if drafts
                             else "Double-click a count to see it.")

    def _selected(self):
        r = selected_row(self.table)
        return self.rows[r] if r is not None else None

    def new_count(self) -> None:
        dlg = NewCountDialog(self.services, self.session, self)
        if dlg.exec() and dlg.count_id:
            self.refresh()
            CountSheetDialog(self.services, self.session, dlg.count_id, self).exec()
            self.refresh()

    def open_count(self) -> None:
        row = self._selected()
        if row:
            CountSheetDialog(self.services, self.session, int(row["id"]), self).exec()
            self.refresh()

    def cancel_count(self) -> None:
        row = self._selected()
        if not row or row["status"] != "draft":
            self.summary.setText("Select a count that is still in progress.")
            return
        if confirm(self, "Cancel count", f"Cancel stock count {row['count_no']}? Stock is not changed.",
                   "Cancel count"):
            ok, _ = run(self, self.services.inventory.cancel_count, self.session, int(row["id"]))
            if ok:
                self.refresh()

"""Inventory: what is in stock, what is running low, adjust stock, see movements."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLineEdit

from ui.dialogs.inventory_dialogs import AdjustStockDialog, MovementsDialog
from ui.pages.base import Page
from ui.widgets.common import button, label, run
from ui.widgets.tables import AMBER, RED, fill_table, make_table, qty, selected_row
from utils.money import format_money


class InventoryPage(Page):
    title = "Inventory"
    subtitle = ("Stock on hand. Orange = at or below the reorder level, red = below zero "
                "(sold before it was recorded).")

    def __init__(self, services, session) -> None:
        super().__init__(services, session)
        self.rows = []
        self.symbol = "₱"
        self.show_cost = services.products.can_see_cost(session)
        bar = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Search name, barcode, SKU or brand…")
        self.search.returnPressed.connect(self.refresh)
        self.category = QComboBox()
        self.category.setMinimumWidth(200)
        self.category.currentIndexChanged.connect(lambda _: self.refresh())
        self.low_only = QCheckBox("Low stock only")
        self.low_only.toggled.connect(lambda _: self.refresh())
        bar.addWidget(self.search, 1)
        bar.addWidget(self.category)
        bar.addWidget(self.low_only)
        bar.addWidget(button("Search", self.refresh, "Primary"))
        self.lay.addLayout(bar)

        self.cols = ["SKU", "Product", "Category", "In stock", "Unit", "Reorder at"]
        if self.show_cost:
            self.cols += ["Cost", "Value"]
        self.table = make_table(self.cols, stretch=1)
        self.table.doubleClicked.connect(lambda _: self.open_movements())
        self.lay.addWidget(self.table, 1)

        foot = QHBoxLayout()
        self.summary = label("", "SectionTitle")
        foot.addWidget(self.summary, 1)
        foot.addWidget(button("Movements…", self.open_movements))
        if session.can("inventory.adjust"):
            self.adjust_btn = button("Adjust stock…", self.adjust, None, "Ctrl+J")
            foot.addWidget(self.adjust_btn)
        self.lay.addLayout(foot)

    def on_show(self) -> None:
        ok, s = run(self, self.services.settings.get)
        if ok:
            self.symbol = s.currency_symbol
        ok, cats = run(self, self.services.catalog.list_items, self.session, "category", False)
        if ok:
            current = self.category.currentData()
            self.category.blockSignals(True)
            self.category.clear()
            self.category.addItem("All categories", None)
            for c in cats:
                self.category.addItem(c.name, c.id)
            self.category.setCurrentIndex(max(0, self.category.findData(current)))
            self.category.blockSignals(False)
        self.refresh()

    def refresh(self) -> None:
        ok, rows = run(self, self.services.inventory.stock_list, self.session, self.search.text(),
                       self.category.currentData(), self.low_only.isChecked())
        if not ok:
            return
        self.rows = rows
        m = lambda v: format_money(v, self.symbol)  # noqa: E731
        data, colors = [], []
        for r in rows:
            vals = [r.sku, r.name, r.category_name or "", qty(r.quantity), r.unit_code,
                    qty(r.reorder_level)]
            if self.show_cost:
                vals += [m(r.cost_price), m(r.value)]
            data.append(vals)
            colors.append(RED if r.quantity < 0 else AMBER if r.is_low else None)
        fill_table(self.table, data, {3, 5, 6, 7}, colors)
        ok, s = run(self, self.services.inventory.summary, self.session)
        if ok:
            text = (f"{len(rows)} shown  ·  {s['low']} low  ·  {s['negative']} below zero")
            if "value" in s:
                text += f"  ·  Stock value (at cost): {m(s['value'])}"
            self.summary.setText(text)

    def _selected(self):
        r = selected_row(self.table)
        return self.rows[r] if r is not None else None

    def open_movements(self) -> None:
        row = self._selected()
        if row:
            MovementsDialog(self.services, self.session, row, self.symbol, self).exec()

    def adjust(self) -> None:
        row = self._selected()
        if row is None:
            self.summary.setText("Select a product first.")
            return
        if AdjustStockDialog(self.services, self.session, row, self).exec():
            index = self.rows.index(row)
            self.refresh()
            if index < self.table.rowCount():
                self.table.selectRow(index)

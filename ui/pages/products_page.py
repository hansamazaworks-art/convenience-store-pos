"""Product list with search, barcode lookup and editing."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLineEdit, QTableWidget,
    QTableWidgetItem,
)

from models.product import Product
from ui.dialogs.product_dialogs import PriceHistoryDialog, ProductDialog
from ui.pages.base import Page
from ui.widgets.common import button, button_row, confirm, label, run
from utils.money import format_money

LIMIT = 500


class ProductsPage(Page):
    title = "Products"
    subtitle = "Search by name, brand, SKU, or scan a barcode into the search box."

    def __init__(self, services, session) -> None:
        super().__init__(services, session)
        self.can_manage = session.can("products.manage")
        self.show_cost = services.products.can_see_cost(session)
        self.products: list[Product] = []
        self.symbol = "₱"

        # ---- search bar
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit(placeholderText="Search or scan barcode…  (F3)")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self._on_enter)
        self._debounce = QTimer(self, singleShot=True, interval=250, timeout=self.refresh)
        self.search.textChanged.connect(lambda _: self._debounce.start())
        self.category = QComboBox()
        self.category.setMinimumWidth(200)
        self.category.currentIndexChanged.connect(lambda _: self.refresh())
        self.inactive = QCheckBox("Show inactive")
        self.inactive.toggled.connect(lambda _: self.refresh())
        bar.addWidget(self.search, 1)
        bar.addWidget(self.category)
        bar.addWidget(self.inactive)
        self.lay.addLayout(bar)

        # ---- action buttons (only for people who may change products)
        if self.can_manage:
            self.add_btn = button("+ Add product", self.add_product, "Primary", "Ctrl+N")
            self.edit_btn = button("Edit", self.edit_product)
            self.toggle_btn = button("Deactivate", self.toggle_active)
            self.history_btn = button("Price history", self.show_history)
            self.lay.addLayout(button_row(self.add_btn, self.edit_btn, self.toggle_btn,
                                          self.history_btn, stretch_first=False))

        # ---- table
        cols = ["Name", "Brand", "Category", "Barcode", "SKU", "Unit"]
        if self.show_cost:
            cols += ["Cost", "Price", "Margin"]
        else:
            cols += ["Price"]
        cols += ["Status"]
        self.cols = cols
        self.table = QTableWidget(0, len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for i in range(len(cols)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        if self.can_manage:
            self.table.doubleClicked.connect(lambda _: self.edit_product())
        self.lay.addWidget(self.table, 1)
        self.count = label("", "Muted")
        self.lay.addWidget(self.count)

        from PySide6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence("F3"), self, activated=self._focus_search)
        self._update_buttons()

    # ------------------------------------------------------------------ data
    def on_show(self) -> None:
        ok, s = run(self, self.services.settings.get)
        if ok:
            self.symbol = s.currency_symbol
        self._load_categories()
        self.refresh()
        self._focus_search()

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _load_categories(self) -> None:
        ok, cats = run(self, self.services.catalog.list_items, self.session, "category", False)
        if not ok:
            return
        current = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("All categories", None)
        for c in cats:
            self.category.addItem(c.name, c.id)
        self.category.setCurrentIndex(max(0, self.category.findData(current)))
        self.category.blockSignals(False)

    def refresh(self, select_id: int | None = None) -> None:
        ok, products = run(self, self.services.products.search, self.session,
                           self.search.text(), self.category.currentData(),
                           self.inactive.isChecked(), LIMIT)
        if not ok:
            return
        current = select_id or (self.selected().id if self.selected() else None)
        self.products = products
        self.table.setRowCount(len(products))
        right = Qt.AlignRight | Qt.AlignVCenter
        for r, p in enumerate(products):
            vals: list[tuple[str, int | None]] = [
                (p.name, None), (p.brand_name or "", None), (p.category_name or "", None),
                (p.barcode or "", None), (p.sku, None), (p.unit_code, None)]
            if self.show_cost:
                vals += [(format_money(p.cost_price, self.symbol), right),
                         (format_money(p.selling_price, self.symbol), right),
                         (f"{p.margin_percent:.1f}%" if p.margin_percent is not None else "", right)]
            else:
                vals += [(format_money(p.selling_price, self.symbol), right)]
            vals += [("Active" if p.is_active else "Inactive", None)]
            for c, (v, align) in enumerate(vals):
                item = QTableWidgetItem(v)
                if align:
                    item.setTextAlignment(align)
                if not p.is_active:
                    item.setForeground(Qt.gray)
                if self.show_cost and c == 8 and p.margin_percent is not None and p.margin_percent < 0:
                    item.setForeground(Qt.red)
                self.table.setItem(r, c, item)
            if p.id == current:
                self.table.selectRow(r)
        if len(products) == 1 and current is None:
            self.table.selectRow(0)
        more = f" (showing the first {LIMIT}; type more to narrow the search)" \
            if len(products) >= LIMIT else ""
        self.count.setText(f"{len(products)} product{'s' if len(products) != 1 else ''}{more}")
        self._update_buttons()

    def selected(self) -> Product | None:
        sm = self.table.selectionModel()
        rows = sm.selectedRows() if sm else []
        if not rows or rows[0].row() >= len(self.products):
            return None
        return self.products[rows[0].row()]

    def _update_buttons(self) -> None:
        if not self.can_manage:
            return
        p = self.selected()
        for b in (self.edit_btn, self.toggle_btn, self.history_btn):
            b.setEnabled(p is not None)
        self.toggle_btn.setText("Activate" if (p and not p.is_active) else "Deactivate")

    # --------------------------------------------------------------- actions
    def _on_enter(self) -> None:
        """Enter in the search box (a barcode scanner sends Enter after the code)."""
        self._debounce.stop()
        code = self.search.text().strip()
        if not code:
            return
        ok, found = run(self, self.services.products.find_by_code, self.session, code)
        if not ok:
            return
        if found:
            self.refresh(found.id)
            return
        self.refresh()
        if not self.products and self.can_manage and " " not in code and confirm(
                self, "Product not found",
                f"No product has the barcode or SKU '{code}'.\n\nAdd a new product with this barcode?",
                "Add product"):
            self.add_product(barcode=code)

    def add_product(self, barcode: str = "") -> None:
        dlg = ProductDialog(self.services, self.session, barcode=barcode, parent=self)
        if dlg.exec():
            self.search.clear()
            self.refresh(dlg.product_id)
            self._focus_search()

    def edit_product(self) -> None:
        p = self.selected()
        if p is None or not self.can_manage:
            return
        ok, fresh = run(self, self.services.products.get, self.session, p.id)
        if ok and ProductDialog(self.services, self.session, fresh, parent=self).exec():
            self.refresh(p.id)

    def toggle_active(self) -> None:
        p = self.selected()
        if p is None:
            return
        activate = not p.is_active
        if not activate and not confirm(
                self, "Deactivate product",
                f"Deactivate '{p.name}'?\n\nIt will no longer appear in searches or at the "
                "checkout. Its sales history is kept, and you can activate it again later.",
                "Deactivate"):
            return
        ok, _ = run(self, self.services.products.set_active, self.session, p.id, activate)
        if ok:
            if not activate and not self.inactive.isChecked():
                self.refresh()
            else:
                self.refresh(p.id)

    def show_history(self) -> None:
        p = self.selected()
        if p:
            PriceHistoryDialog(self.services, self.session, p, self).exec()

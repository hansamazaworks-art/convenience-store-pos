"""Add/edit product, price history, and small catalog dialogs."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from models.product import Product
from models.user import Session
from services.container import Services
from services.product_service import BelowCostWarning, ProductInput
from ui.dialogs.account_dialogs import _FormDialog
from ui.widgets.common import button, button_row, confirm, label, run
from ui.widgets.inputs import MoneyEdit, QuantityEdit
from utils.money import format_money


def _fill_combo(combo: QComboBox, items, current_id, none_text: str | None) -> None:
    combo.clear()
    if none_text is not None:
        combo.addItem(none_text, None)
    for it in items:
        if it.is_active or it.id == current_id:
            combo.addItem(it.name + ("" if it.is_active else " (inactive)"), it.id)
    idx = combo.findData(current_id)
    combo.setCurrentIndex(idx if idx >= 0 else 0)


class ProductDialog(_FormDialog):
    """Create or edit a product. All checks happen in ProductService."""

    def __init__(self, services: Services, session: Session, product: Product | None = None,
                 barcode: str = "", parent: QWidget | None = None) -> None:
        editing = product is not None
        super().__init__(parent, "Edit product" if editing else "Add product",
                         "Tip: click in the Barcode box and scan the item." if not editing else "",
                         "Save" if editing else "Add product")
        self.setMinimumWidth(620)
        self.services, self.session, self.product = services, session, product
        self.product_id: int | None = product.id if product else None
        self.symbol = services.settings.get().currency_symbol

        self.name = QLineEdit(product.name if product else "")
        self.name.setMaxLength(150)
        self.barcode = QLineEdit((product.barcode or "") if product else barcode)
        self.barcode.setMaxLength(50)
        self.barcode.setPlaceholderText("Scan or type the barcode (optional)")
        self.sku = QLineEdit(product.sku if product else "")
        self.sku.setMaxLength(40)
        self.sku.setPlaceholderText("Automatic if left empty")
        self.category = QComboBox()
        self.brand = QComboBox()
        self.unit = QComboBox()
        self.cost = MoneyEdit()
        self.price = MoneyEdit()
        if product:
            self.cost.setText(f"{product.cost_price:.2f}" if product.cost_price is not None else "")
            self.price.setText(f"{product.selling_price:.2f}")
        self.margin = label("", "Muted")
        self.reorder = QuantityEdit("0")
        if product and product.reorder_level:
            self.reorder.setText(f"{product.reorder_level.normalize():f}")
        self.track_expiry = QCheckBox("This product has expiry dates (track them when receiving stock)")
        self.track_expiry.setChecked(bool(product and product.track_expiry))

        self._load_lists()

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)

        def add(row, col, caption, widget, span=1):
            grid.addWidget(label(caption), row * 2, col, 1, span)
            grid.addWidget(widget, row * 2 + 1, col, 1, span)

        add(0, 0, "Product name *", self.name, 2)
        add(1, 0, "Barcode", self.barcode)
        add(1, 1, "SKU (store code)", self.sku)
        add(2, 0, "Category", self._with_new(self.category, "category"))
        add(2, 1, "Brand", self._with_new(self.brand, "brand"))
        add(3, 0, f"Cost price ({self.symbol})", self.cost)
        add(3, 1, f"Selling price ({self.symbol}) *", self.price)
        grid.addWidget(self.margin, 8, 0, 1, 2)
        add(5, 0, "Sold by (unit) *", self.unit)
        add(5, 1, "Reorder when stock falls to", self.reorder)
        # Expiry dates are not tracked (owner's decision); the flag is kept as it was.
        self.form.addRow(grid)

        self.cost.textChanged.connect(self._update_margin)
        self.price.textChanged.connect(self._update_margin)
        self._update_margin()
        (self.name if editing or barcode else self.barcode).setFocus()

    # --------------------------------------------------------------- helpers
    def _with_new(self, combo: QComboBox, kind: str) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(combo, 1)
        b = button("New…", lambda: self._new_item(kind, combo))
        b.setToolTip(f"Add a new {kind}")
        row.addWidget(b)
        return w

    def _load_lists(self) -> None:
        p = self.product
        cats = self.services.catalog.list_items(self.session, "category")
        brands = self.services.catalog.list_items(self.session, "brand")
        units = self.services.catalog.list_units(self.session)
        _fill_combo(self.category, cats, p.category_id if p else None, "— No category —")
        _fill_combo(self.brand, brands, p.brand_id if p else None, "— No brand —")
        self.unit.clear()
        for u in units:
            if u.is_active or (p and u.id == p.unit_id):
                self.unit.addItem(f"{u.name} ({u.code})", u.id)
        default_unit = p.unit_id if p else next((u.id for u in units if u.code == "pc"), None)
        self.unit.setCurrentIndex(max(0, self.unit.findData(default_unit)))

    def _new_item(self, kind: str, combo: QComboBox) -> None:
        name, ok = QInputDialog.getText(self, f"New {kind}", f"Name of the new {kind}:")
        if not ok or not name.strip():
            return
        ok, new_id = run(self, self.services.catalog.save_item, self.session, kind, name)
        if ok:
            items = self.services.catalog.list_items(self.session, kind)
            _fill_combo(combo, items, new_id, f"— No {kind} —")

    def _update_margin(self) -> None:
        try:
            cost = Decimal(self.cost.text() or "0")
            price = Decimal(self.price.text() or "0")
        except InvalidOperation:
            self.margin.setText("")
            return
        if price <= 0:
            self.margin.setText("")
            return
        profit = price - cost
        pct = (profit / price * 100).quantize(Decimal("0.1"))
        self.margin.setText(f"Profit per unit: {format_money(profit, self.symbol)}   "
                            f"(margin {pct}%)" + ("   ⚠ below cost" if profit < 0 else ""))
        self.margin.setObjectName("ErrorText" if profit < 0 else "Muted")
        self.margin.style().unpolish(self.margin)
        self.margin.style().polish(self.margin)

    def _input(self, allow_below_cost: bool = False) -> ProductInput:
        return ProductInput(
            name=self.name.text(), unit_id=self.unit.currentData(),
            selling_price=self.price.text(), cost_price=self.cost.text() or "0",
            sku=self.sku.text(), barcode=self.barcode.text(),
            category_id=self.category.currentData(), brand_id=self.brand.currentData(),
            reorder_level=self.reorder.text() or "0", track_expiry=self.track_expiry.isChecked(),
            allow_below_cost=allow_below_cost,
        )

    def submit(self) -> None:
        def save(allow: bool):
            if self.product_id is None:
                self.product_id = self.services.products.create(self.session, self._input(allow))
            else:
                self.services.products.update(self.session, self.product_id, self._input(allow))
        try:
            save(False)
        except BelowCostWarning as w:
            if not confirm(self, "Price below cost", w.user_message + "\n\nSave anyway?",
                           "Save anyway"):
                raise
            save(True)


class PriceHistoryDialog(QDialog):
    def __init__(self, services: Services, session: Session, product: Product,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Price history - {product.name}")
        self.resize(760, 420)
        sym = services.settings.get().currency_symbol
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.addWidget(label(f"Price history - {product.name}", "SectionTitle"))
        cols = ["Date", "Changed by", "Cost", "Selling price", "Reason"]
        table = QTableWidget(0, len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        ok, rows = run(self, services.products.price_history, session, product.id)
        rows = rows or []

        def change(old, new):
            new_s = format_money(new, sym)
            return new_s if old is None or old == new else f"{format_money(old, sym)} → {new_s}"

        table.setRowCount(len(rows))
        for r, h in enumerate(rows):
            vals = [h["changed_at"].strftime("%d %b %Y %H:%M"), h["changed_by"] or "",
                    change(h["old_cost_price"], h["new_cost_price"]),
                    change(h["old_selling_price"], h["new_selling_price"]), h["reason"]]
            for c, v in enumerate(vals):
                table.setItem(r, c, QTableWidgetItem(v))
        lay.addWidget(table, 1)
        lay.addLayout(button_row(button("Close", self.accept, "Primary")))


class UnitDialog(_FormDialog):
    def __init__(self, services: Services, session: Session, unit=None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent, "Edit unit" if unit else "Add unit",
                         "How a product is counted when sold, e.g. Piece (pc) or Kilogram (kg).",
                         "Save")
        self.services, self.session, self.unit = services, session, unit
        self.code = QLineEdit(unit.code if unit else "")
        self.code.setMaxLength(10)
        self.code.setPlaceholderText("e.g. dz")
        self.name = QLineEdit(unit.name if unit else "")
        self.name.setMaxLength(40)
        self.name.setPlaceholderText("e.g. Dozen")
        self.decimal = QCheckBox("Can be sold in fractions (e.g. 0.25 kg)")
        self.decimal.setChecked(bool(unit and unit.allow_decimal))
        self.form.addRow("Short code", self.code)
        self.form.addRow("Name", self.name)
        self.form.addRow(self.decimal)

    def submit(self) -> None:
        self.services.catalog.save_unit(
            self.session, self.code.text(), self.name.text(), self.decimal.isChecked(),
            self.unit.id if self.unit else None, self.unit.is_active if self.unit else True)

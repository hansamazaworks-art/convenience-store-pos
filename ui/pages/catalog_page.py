"""Categories, brands and units - one tab each."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QInputDialog, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from ui.dialogs.product_dialogs import UnitDialog
from ui.pages.base import Page
from ui.widgets.common import button, button_row, run


def _table(cols: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(cols))
    t.setHorizontalHeaderLabels(cols)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().hide()
    t.verticalHeader().setDefaultSectionSize(34)
    hh = t.horizontalHeader()
    hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    hh.setSectionResizeMode(QHeaderView.ResizeToContents)
    hh.setSectionResizeMode(0, QHeaderView.Stretch)
    return t


class _ListTab(QWidget):
    """Categories or brands."""

    def __init__(self, page: "CatalogPage", kind: str, title: str) -> None:
        super().__init__()
        self.page, self.kind, self.title = page, kind, title
        self.items = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        self.add_btn = button(f"+ Add {kind}", self.add, "Primary")
        self.rename_btn = button("Rename", self.rename)
        self.toggle_btn = button("Deactivate", self.toggle)
        lay.addLayout(button_row(self.add_btn, self.rename_btn, self.toggle_btn, stretch_first=False))
        self.table = _table(["Name", "Products", "Status"])
        self.table.itemSelectionChanged.connect(self._update)
        self.table.doubleClicked.connect(lambda _: self.rename())
        lay.addWidget(self.table, 1)

    def refresh(self, select_id=None) -> None:
        ok, items = run(self, self.page.services.catalog.list_items, self.page.session, self.kind)
        if not ok:
            return
        cur = select_id or (self.selected().id if self.selected() else None)
        self.items = items
        self.table.setRowCount(len(items))
        for r, it in enumerate(items):
            for c, v in enumerate([it.name, str(it.product_count),
                                   "Active" if it.is_active else "Inactive"]):
                cell = QTableWidgetItem(v)
                if not it.is_active:
                    cell.setForeground(Qt.gray)
                self.table.setItem(r, c, cell)
            if it.id == cur:
                self.table.selectRow(r)
        self._update()

    def selected(self):
        sm = self.table.selectionModel()
        rows = sm.selectedRows() if sm else []
        return self.items[rows[0].row()] if rows and rows[0].row() < len(self.items) else None

    def _update(self) -> None:
        it = self.selected()
        self.rename_btn.setEnabled(it is not None)
        self.toggle_btn.setEnabled(it is not None)
        self.toggle_btn.setText("Activate" if it and not it.is_active else "Deactivate")

    def _save(self, name: str, item=None, active: bool = True) -> None:
        ok, new_id = run(self, self.page.services.catalog.save_item, self.page.session, self.kind,
                         name, item.id if item else None, active)
        if ok:
            self.refresh(new_id)

    def add(self) -> None:
        name, ok = QInputDialog.getText(self, f"Add {self.kind}", f"Name of the new {self.kind}:")
        if ok and name.strip():
            self._save(name)

    def rename(self) -> None:
        it = self.selected()
        if it is None:
            return
        name, ok = QInputDialog.getText(self, f"Rename {self.kind}", "New name:", text=it.name)
        if ok and name.strip():
            self._save(name, it, it.is_active)

    def toggle(self) -> None:
        it = self.selected()
        if it:
            self._save(it.name, it, not it.is_active)


class _UnitsTab(QWidget):
    def __init__(self, page: "CatalogPage") -> None:
        super().__init__()
        self.page = page
        self.units = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        self.add_btn = button("+ Add unit", self.add, "Primary")
        self.edit_btn = button("Edit", self.edit)
        self.toggle_btn = button("Deactivate", self.toggle)
        lay.addLayout(button_row(self.add_btn, self.edit_btn, self.toggle_btn, stretch_first=False))
        self.table = _table(["Name", "Code", "Fractions allowed", "Products", "Status"])
        self.table.itemSelectionChanged.connect(self._update)
        self.table.doubleClicked.connect(lambda _: self.edit())
        lay.addWidget(self.table, 1)

    def refresh(self, select_id=None) -> None:
        ok, units = run(self, self.page.services.catalog.list_units, self.page.session)
        if not ok:
            return
        cur = select_id or (self.selected().id if self.selected() else None)
        self.units = units
        self.table.setRowCount(len(units))
        for r, u in enumerate(units):
            for c, v in enumerate([u.name, u.code, "Yes" if u.allow_decimal else "No",
                                   str(u.product_count), "Active" if u.is_active else "Inactive"]):
                cell = QTableWidgetItem(v)
                if not u.is_active:
                    cell.setForeground(Qt.gray)
                self.table.setItem(r, c, cell)
            if u.id == cur:
                self.table.selectRow(r)
        self._update()

    def selected(self):
        sm = self.table.selectionModel()
        rows = sm.selectedRows() if sm else []
        return self.units[rows[0].row()] if rows and rows[0].row() < len(self.units) else None

    def _update(self) -> None:
        u = self.selected()
        self.edit_btn.setEnabled(u is not None)
        self.toggle_btn.setEnabled(u is not None)
        self.toggle_btn.setText("Activate" if u and not u.is_active else "Deactivate")

    def add(self) -> None:
        if UnitDialog(self.page.services, self.page.session, parent=self).exec():
            self.refresh()

    def edit(self) -> None:
        u = self.selected()
        if u and UnitDialog(self.page.services, self.page.session, u, parent=self).exec():
            self.refresh(u.id)

    def toggle(self) -> None:
        u = self.selected()
        if u:
            ok, _ = run(self, self.page.services.catalog.save_unit, self.page.session, u.code,
                        u.name, u.allow_decimal, u.id, not u.is_active)
            if ok:
                self.refresh(u.id)


class CatalogPage(Page):
    title = "Categories & brands"
    subtitle = ("Lists used when adding products. Deactivating hides an entry from new products; "
                "existing products keep it.")

    def __init__(self, services, session) -> None:
        super().__init__(services, session)
        self.tabs = QTabWidget()
        self.category_tab = _ListTab(self, "category", "Categories")
        self.brand_tab = _ListTab(self, "brand", "Brands")
        self.unit_tab = _UnitsTab(self)
        self.tabs.addTab(self.category_tab, "Categories")
        self.tabs.addTab(self.brand_tab, "Brands")
        self.tabs.addTab(self.unit_tab, "Units")
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget().refresh())
        self.lay.addWidget(self.tabs, 1)

    def on_show(self) -> None:
        self.tabs.currentWidget().refresh()

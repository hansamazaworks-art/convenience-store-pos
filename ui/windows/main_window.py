"""Main window: menu on the left, the chosen screen on the right."""
from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from models.user import Session
from services.container import Services
from ui.dialogs.account_dialogs import ChangePasswordDialog
from ui.dialogs.receipt_dialogs import show_sale_receipt
from ui.pages.audit_page import AuditPage
from ui.pages.base import Page
from ui.pages.catalog_page import CatalogPage
from ui.pages.dashboard_page import DashboardPage
from ui.pages.inventory_page import InventoryPage
from ui.pages.pos_page import PosPage
from ui.pages.products_page import ProductsPage
from ui.pages.receive_page import ReceivePage
from ui.pages.reports_page import DailyReportPage
from ui.pages.sales_history_page import SalesHistoryPage
from ui.pages.settings_page import SettingsPage
from ui.pages.shift_pages import ExpensesPage, MyShiftPage, ShiftsPage
from ui.pages.stock_count_page import StockCountPage
from ui.pages.suppliers_page import SuppliersPage
from ui.pages.users_page import UsersPage
from ui.widgets.common import button, info, label


class MainWindow(QMainWindow):
    def __init__(self, services: Services, session: Session,
                 on_logout: Callable[[], None]) -> None:
        super().__init__()
        self.services = services
        self.session = session
        self._on_logout = on_logout
        self._logging_out = False
        self.setMinimumSize(1024, 680)

        # (key, menu text, required permission, page factory). A menu entry is only
        # created when the user has the permission - no dead buttons.
        nav = [
            ("dashboard", "Dashboard", None, lambda: DashboardPage(services, session)),
            ("pos", "Checkout", "pos.sell", lambda: PosPage(services, session)),
            ("shift", "My shift", "shifts.own", lambda: MyShiftPage(services, session)),
            ("sales", "Sales history", "pos.sell",
             lambda: SalesHistoryPage(services, session, on_reprint=lambda sid: show_sale_receipt(
                 self, services, self.session, sid))),
            ("products", "Products", "products.view", lambda: ProductsPage(services, session)),
            ("inventory", "Inventory", "inventory.view", lambda: InventoryPage(services, session)),
            ("stock_count", "Stock count", "inventory.count", lambda: StockCountPage(services, session)),
            ("receive", "Receive stock", "purchasing.receive", lambda: ReceivePage(services, session)),
            ("suppliers", "Suppliers", "suppliers.manage", lambda: SuppliersPage(services, session)),
            ("shifts", "Shifts", "shifts.manage", lambda: ShiftsPage(services, session)),
            ("expenses", "Expenses", "expenses.manage", lambda: ExpensesPage(services, session)),
            ("reports", "Daily report", "reports.sales", lambda: DailyReportPage(services, session)),
            ("catalog", "Categories & brands", "products.manage",
             lambda: CatalogPage(services, session)),
            ("users", "Users", "users.manage", lambda: UsersPage(services, session)),
            ("settings", "Store settings", "settings.manage",
             lambda: SettingsPage(services, session, on_saved=self._refresh_title)),
            ("audit", "Audit log", "audit.view", lambda: AuditPage(services, session)),
        ]

        # ---- sidebar
        sidebar = QWidget(objectName="Sidebar")
        sidebar.setFixedWidth(220)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 18, 12, 14)
        side.setSpacing(4)
        self.store_label = label("", "SidebarTitle", wrap=True)
        side.addWidget(self.store_label)
        side.addWidget(label("Point of Sale", "SidebarSub"))
        side.addSpacing(18)

        self.stack = QStackedWidget()
        self.pages: dict[str, Page] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        index = 0
        for key, text, perm, factory in nav:
            if perm and not session.can(perm):
                continue
            index += 1
            page = factory()
            self.pages[key] = page
            self.stack.addWidget(page)
            b = QPushButton(text.replace("&", "&&"), objectName="NavButton", checkable=True)
            b.clicked.connect(lambda _=False, k=key: self.open_page(k))
            if index <= 9:
                b.setToolTip(f"Shortcut: Ctrl+{index}")
                QShortcut(QKeySequence(f"Ctrl+{index}"), self, activated=b.click)
            group.addButton(b)
            side.addWidget(b)
            self.nav_buttons[key] = b
        side.addStretch()

        # ---- top bar
        top = QWidget(objectName="TopBar")
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(24, 10, 16, 10)
        top_lay.setSpacing(10)
        top_lay.addStretch()
        top_lay.addWidget(label(session.full_name, "SectionTitle"))
        top_lay.addWidget(label(session.role_name, "Chip"))
        top_lay.addSpacing(8)
        top_lay.addWidget(button("Change password", self.change_password, "Link"))
        self.logout_btn = button("Log out", self.logout, None, "Ctrl+L")
        top_lay.addWidget(self.logout_btn)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        right_lay.addWidget(top)
        right_lay.addWidget(self.stack, 1)

        root = QWidget()
        root_lay = QHBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)
        root_lay.addWidget(sidebar)
        root_lay.addWidget(right, 1)
        self.setCentralWidget(root)

        self._refresh_title()
        self.open_page("dashboard")

    # ---------------------------------------------------------------- actions
    def open_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.nav_buttons[key].setChecked(True)
        self.stack.setCurrentWidget(page)
        page.on_show()

    def _refresh_title(self) -> None:
        name = self.services.settings.get().store_name
        self.store_label.setText(name)
        self.setWindowTitle(f"{name} - POS  ({self.session.full_name})")

    def change_password(self) -> None:
        dlg = ChangePasswordDialog(self.services, self.session, self)
        if dlg.exec():
            self.session = dlg.session
            info(self, "Password changed", "Your password was changed.")

    def _open_sale(self) -> bool:
        pos = self.pages.get("pos")
        return bool(pos is not None and pos.has_open_sale)

    def logout(self) -> None:
        if self._open_sale():
            self.open_page("pos")
            info(self, "Sale in progress",
                 "Finish, hold (F8) or cancel (F10) the current sale before logging out.")
            return
        self._logging_out = True
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if self._open_sale() and not self._logging_out:
            self.open_page("pos")
            info(self, "Sale in progress",
                 "Finish, hold (F8) or cancel (F10) the current sale before closing the POS.")
            event.ignore()
            return
        self.services.auth.logout(self.session)
        if self._logging_out:
            self._on_logout()
        event.accept()

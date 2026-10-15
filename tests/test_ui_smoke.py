"""Drive the real screens off-screen against a test database."""
import os
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

pytestmark = pytest.mark.integration
PW = "Owner-Pass-1"
ADMIN_PAGES = {"dashboard", "pos", "shift", "sales", "products", "inventory", "stock_count", "receive",
               "suppliers", "shifts", "expenses", "reports", "catalog", "users", "settings", "audit"}


@pytest.fixture(scope="module")
def qapp():
    from ui.styles import APP_STYLESHEET
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLESHEET)
    return app


@pytest.fixture()
def services(test_db_settings, qapp, monkeypatch):
    from config.settings import DatabaseSettings
    from database.connection import Database
    from database.migrator import Migrator
    from services.container import Services
    # Never block on a message box during tests; remember what would have been shown.
    shown = []
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name,
                            staticmethod(lambda *a, _n=name, **k: shown.append((_n, a[1:]))))
    name = f"pos_pytest_{uuid.uuid4().hex[:10]}"
    cfg = DatabaseSettings(**{**test_db_settings.__dict__, "name": name})
    server = Database(cfg, use_database=False)
    server.execute(f"CREATE DATABASE `{name}`")
    db = Database(cfg)
    Migrator(db).migrate()
    s = Services.build(db)
    s.shown = shown
    yield s
    for w in QApplication.topLevelWidgets():   # close every window the test opened
        w.hide()
        w.deleteLater()
    QApplication.processEvents()
    server.execute(f"DROP DATABASE IF EXISTS `{name}`")


def test_first_admin_dialog_and_main_window_for_admin(services):
    from ui.dialogs.account_dialogs import FirstAdminDialog
    from ui.windows.main_window import MainWindow
    dlg = FirstAdminDialog(services)
    dlg.full_name.setText("Store Owner")
    dlg.username.setText("owner")
    dlg.pw1.setText(PW)
    dlg.pw2.setText("different")
    dlg._on_ok()
    assert dlg.error.isVisibleTo(dlg) and "do not match" in dlg.error.text()
    dlg.pw2.setText(PW)
    dlg._on_ok()
    assert dlg.session and dlg.session.role_code == "admin"

    logged_out = []
    win = MainWindow(services, dlg.session, on_logout=lambda: logged_out.append(1))
    assert set(win.pages) == ADMIN_PAGES
    for key in win.pages:
        win.open_page(key)
    assert "Owner" in win.pages["dashboard"].values["user"].text()
    assert win.pages["users"].table.rowCount() == 1
    assert win.pages["audit"].table.rowCount() >= 2
    win.logout()
    assert logged_out == [1]


def test_users_page_create_user_and_cashier_sees_less(services):
    from ui.dialogs.account_dialogs import ChangePasswordDialog, UserDialog
    from ui.pages.users_page import UsersPage
    from ui.windows.login_window import LoginWindow
    from ui.windows.main_window import MainWindow
    admin = services.auth.create_first_admin("owner", "Owner", PW)
    page = UsersPage(services, admin)
    page.on_show()
    roles = services.users.list_roles(admin)
    dlg = UserDialog(services, admin, roles, parent=page)
    dlg.full_name.setText("Ana Reyes")
    dlg.username.setText("ana")
    assert roles[dlg.role.currentIndex()].code == "cashier"  # sensible default
    temp = dlg.temp.text()
    assert len(temp) >= 8
    dlg._on_ok()
    assert dlg.result() == dlg.DialogCode.Accepted
    page.refresh()
    assert page.table.rowCount() == 2

    # login screen: wrong password shows inline error, right one logs in
    got = []
    login = LoginWindow(services, "Test Store", on_success=got.append)
    login.username.setText("ana")
    login.password.setText("wrong-password")
    login.attempt()
    assert not got and "Wrong username or password" in login.error.text()
    login.password.setText(temp)
    login.attempt()
    cashier = got[0]
    assert cashier.must_change_password

    cp = ChangePasswordDialog(services, cashier, forced=True)
    cp.current.setText(temp)
    cp.pw1.setText("Ana-Own-Pass")
    cp.pw2.setText("Ana-Own-Pass")
    cp._on_ok()
    assert not cp.session.must_change_password

    win = MainWindow(services, cp.session, on_logout=lambda: None)
    assert set(win.pages) == {"dashboard", "pos", "shift", "sales", "products"}  # no Users / Settings / Audit for a cashier
    win.close()


def test_settings_page_saves(services):
    from ui.pages.settings_page import SettingsPage
    admin = services.auth.create_first_admin("owner", "Owner", PW)
    saved = []
    page = SettingsPage(services, admin, on_saved=lambda: saved.append(1))
    page.on_show()
    page.fields["store_name"].setText("Sample Corner")
    page.fields["currency_symbol"].setText("S$")
    page.save()
    assert saved == [1]
    assert services.settings.get().store_name == "Sample Corner"
    page.fields["store_name"].setText("   ")
    page.save()
    assert services.shown[-1][0] == "warning"  # friendly validation message, not a crash
    assert services.settings.get().store_name == "Sample Corner"


def test_last_admin_disable_shows_message(services, monkeypatch):
    from ui.pages.users_page import UsersPage
    import ui.pages.users_page as up
    admin = services.auth.create_first_admin("owner", "Owner", PW)
    page = UsersPage(services, admin)
    page.on_show()
    page.table.selectRow(0)
    monkeypatch.setattr(up, "confirm", lambda *a, **k: True)
    page.toggle_active()
    assert services.shown and "own account" in services.shown[-1][1][1]


def test_products_page_add_scan_edit_and_cashier_view(services, monkeypatch):
    from decimal import Decimal
    import ui.pages.products_page as pp
    from ui.dialogs.product_dialogs import ProductDialog
    from ui.pages.catalog_page import CatalogPage
    from ui.pages.products_page import ProductsPage
    admin = services.auth.create_first_admin("owner", "Owner", PW)
    page = ProductsPage(services, admin)
    page.on_show()
    assert "Cost" in page.cols and page.table.rowCount() == 0

    # Scanning an unknown barcode offers to add it, with the barcode filled in.
    opened = []
    monkeypatch.setattr(pp, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(page, "add_product", lambda barcode="": opened.append(barcode))
    page.search.setText("4800016644504")
    page._on_enter()
    assert opened == ["4800016644504"]

    dlg = ProductDialog(services, admin, barcode="4800016644504", parent=page)
    assert dlg.barcode.text() == "4800016644504" and dlg.unit.currentText().startswith("Piece")
    dlg.name.setText("Lucky Me Pancit Canton")
    dlg.category.setCurrentIndex(dlg.category.findText("Instant Noodles"))
    dlg.cost.setText("13.25")
    dlg.price.setText("17")
    assert "margin 22.1%" in dlg.margin.text()
    dlg._on_ok()
    assert dlg.result() == dlg.DialogCode.Accepted, dlg.error.text()

    # below-cost price: declined confirmation keeps the dialog open with a message
    import ui.dialogs.product_dialogs as pd
    monkeypatch.setattr(pd, "confirm", lambda *a, **k: False)
    d2 = ProductDialog(services, admin, parent=page)
    d2.name.setText("Promo item")
    d2.cost.setText("10")
    d2.price.setText("8")
    assert "below cost" in d2.margin.text()
    d2._on_ok()
    assert d2.result() != d2.DialogCode.Accepted and "lower than the cost" in d2.error.text()

    page.search.clear()
    page.refresh()
    assert page.table.rowCount() == 1
    page.search.setText("4800016644504")
    page._on_enter()
    assert page.selected().name == "Lucky Me Pancit Canton"

    ed = ProductDialog(services, admin, services.products.get(admin, page.selected().id), parent=page)
    assert ed.cost.text() == "13.25" and ed.price.text() == "17.00"
    ed.price.setText("18")
    ed._on_ok()
    assert services.products.get(admin, page.selected().id).selling_price == Decimal("18.00")

    cat = CatalogPage(services, admin)
    cat.on_show()
    assert cat.category_tab.table.rowCount() >= 10
    cat.tabs.setCurrentIndex(2)
    assert cat.unit_tab.table.rowCount() >= 9

    roles = {r.code: r.id for r in services.users.list_roles(admin)}
    services.users.create_user(admin, username="cash1", full_name="C", role_id=roles["cashier"],
                               temporary_password="TempPass-1")
    cashier = services.auth.login("cash1", "TempPass-1")
    cp = ProductsPage(services, cashier)
    cp.on_show()
    assert "Cost" not in cp.cols and not hasattr(cp, "add_btn") and cp.table.rowCount() == 1


def test_main_window_menu_per_role(services):
    from ui.windows.main_window import MainWindow
    admin = services.auth.create_first_admin("owner", "Owner", PW)
    roles = {r.code: r.id for r in services.users.list_roles(admin)}
    expected = {
        "cashier": {"dashboard", "pos", "shift", "sales", "products"},
        "inventory": {"dashboard", "products", "catalog", "inventory", "stock_count", "receive"},
        "purchasing": {"dashboard", "products", "inventory", "receive", "suppliers"},
        "manager": {"dashboard", "pos", "shift", "sales", "products", "catalog", "audit", "inventory",
                    "stock_count", "receive", "suppliers", "shifts", "expenses", "reports"},
    }
    for code, pages in expected.items():
        services.users.create_user(admin, username=f"u_{code}", full_name=code,
                                   role_id=roles[code], temporary_password="TempPass-1")
        s = services.auth.login(f"u_{code}", "TempPass-1")
        w = MainWindow(services, s, on_logout=lambda: None)
        assert set(w.pages) == pages, code
        w.close()


def _pos_setup(services):
    from services.product_service import ProductInput
    admin = services.auth.create_first_admin("owner", "Owner", PW)
    roles = {r.code: r.id for r in services.users.list_roles(admin)}
    services.users.create_user(admin, username="cash1", full_name="Ana", role_id=roles["cashier"],
                               temporary_password="TempPass-1")
    services.users.create_user(admin, username="boss", full_name="Ben", role_id=roles["manager"],
                               temporary_password="TempPass-1")
    units = {u.code: u.id for u in services.catalog.list_units(admin)}
    for name, bc, price, unit in [("Coke 290ml", "111", "20", "bottle"),
                                  ("Coke Zero can", "112", "38", "can"),
                                  ("Rice", "333", "56", "kg")]:
        services.products.create(admin, ProductInput(name=name, unit_id=units[unit], cost_price="10",
                                                     selling_price=price, barcode=bc))
    services.settings.update(admin, {"allow_negative_stock": "1"})
    cashier = services.auth.login("cash1", "TempPass-1")
    services.shifts.open_shift(cashier, "1000")
    return admin, cashier


def test_pos_page_full_flow(services, monkeypatch):
    from decimal import Decimal
    import ui.pages.pos_page as pp
    from ui.dialogs import pos_dialogs as pd
    from ui.pages.pos_page import PosPage
    admin, cashier = _pos_setup(services)
    page = PosPage(services, cashier)
    page.on_show()
    assert not page.pay_btn.isEnabled()

    page.scan.setText("111")
    page.on_scan()
    page.scan.setText("3*111")          # quantity prefix merges into the same line
    page.on_scan()
    page.scan.setText("2.5*333")         # kg item with decimals
    page.on_scan()
    assert len(page.cart.lines) == 2 and page.cart.lines[0].quantity == Decimal("4")
    assert page.lbl_total.text() == "₱220.00"   # 4x20 + 2.5x56
    page.scan.setText("nothing-like-this")
    page.on_scan()
    assert "No product found" in page.message.text()

    # several matches -> picker dialog
    picked = []
    monkeypatch.setattr(pd.ProductPickerDialog, "exec",
                        lambda self: (picked.append(len(self.products)), setattr(self, "chosen", [x for x in self.products if "Zero" in x.name][0]), 1)[-1])
    page.scan.setText("coke")
    page.on_scan()
    assert picked == [2] and page.lbl_total.text() == "₱258.00"   # Coke Zero 38 added

    # cashier reducing quantity needs a manager: refuse, then approve
    page.table.selectRow(0)
    monkeypatch.setattr(pp, "authorize", lambda *a, **k: None)
    page.bump_quantity(-1)
    assert page.cart.lines[0].quantity == Decimal("4")
    boss = services.auth.login("boss", "TempPass-1")
    monkeypatch.setattr(pp, "authorize", lambda *a, **k: boss)
    page.table.selectRow(0)
    page.bump_quantity(-1)
    assert page.cart.lines[0].quantity == Decimal("3")
    assert any(r["action"] == "pos.line_voided" for r in services.audit.search(admin, text="voided"))

    # hold and recall
    monkeypatch.setattr(pp.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Blue shirt", True)))
    page.hold()
    assert page.cart.is_empty and "Recall  F9  (1)" == page.btn_recall.text()
    monkeypatch.setattr(pd.HeldSalesDialog, "exec",
                        lambda self: (setattr(self, "chosen_id", int(self.rows[0]["id"])), 1)[-1])
    page.recall()
    assert page.lbl_total.text() == "₱238.00"

    # pay with the real payment dialog (cash 500)
    dlg = pd.PaymentDialog(services, cashier, page.cart, "₱", parent=page)
    assert dlg.amount.text() == "238.00"
    dlg.amount.setText("500")
    assert "Change:  ₱262.00" in dlg.change.text()
    dlg._complete()
    assert dlg.result and dlg.result.change == Decimal("262.00")
    dlg._complete()  # pressing Enter again does not create a second sale
    assert services.db.fetch_one("SELECT COUNT(*) n FROM sales")["n"] == 1


def test_payment_dialog_split_and_errors(services):
    from decimal import Decimal
    from models.cart import Cart
    from ui.dialogs.pos_dialogs import PaymentDialog
    admin, cashier = _pos_setup(services)
    cart = Cart()
    cart.add(services.products.find_by_code(cashier, "112"), "3")   # 114.00
    dlg = PaymentDialog(services, cashier, cart, "₱")
    names = [m.name for m in dlg.methods]
    gcash = names.index("GCash")
    dlg.method_group.button(gcash).click()
    assert dlg.reference.isVisibleTo(dlg) and dlg.amount.text() == "114.00"
    dlg.amount.setText("100")
    dlg._add_split()
    assert "reference number" in dlg.error.text()
    dlg.reference.setText("GC-778899")
    dlg._add_split()
    assert len(dlg.entries) == 1 and "Still due: ₱14.00" in dlg.split_info.text()
    dlg.method_group.button(names.index("Cash")).click()
    dlg.amount.setText("20")
    dlg._complete()
    assert dlg.result.total == Decimal("114.00") and dlg.result.change == Decimal("6.00")


def test_pos_cancel_needs_approval_and_logout_guard(services, monkeypatch):
    import ui.pages.pos_page as pp
    from ui.windows.main_window import MainWindow
    admin, cashier = _pos_setup(services)
    logged_out = []
    win = MainWindow(services, cashier, on_logout=lambda: logged_out.append(1))
    assert {"pos", "sales", "products"} <= set(win.pages)
    page = win.pages["pos"]
    page.scan.setText("111")
    page.on_scan()
    win.logout()
    assert not logged_out  # blocked: sale in progress
    monkeypatch.setattr(pp, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(pp, "authorize", lambda *a, **k: None)
    page.cancel_sale()
    assert not page.cart.is_empty
    monkeypatch.setattr(pp, "authorize", lambda *a, **k: admin)
    page.cancel_sale()
    assert page.cart.is_empty
    win.logout()
    assert logged_out == [1]


def test_sales_history_page(services):
    from models.cart import Cart
    from services.sale_service import PaymentInput
    from ui.pages.sales_history_page import SaleDetailDialog, SalesHistoryPage
    admin, cashier = _pos_setup(services)
    cart = Cart()
    cart.add(services.products.find_by_code(cashier, "111"), "2")
    cash = next(m.id for m in services.sales.payment_methods(cashier) if m.is_cash)
    r = services.sales.complete_sale(cashier, cart, [PaymentInput(cash, "50")])
    page = SalesHistoryPage(services, admin)
    page.on_show()
    assert page.table.rowCount() == 1 and r.sale_no == page.table.item(0, 0).text()
    detail = services.sales.sale_detail(admin, r.sale_id)
    d = SaleDetailDialog(detail, "₱", page)
    assert d.windowTitle() == f"Sale {r.sale_no}"


def test_settings_payment_methods(services, monkeypatch):
    from ui.pages.settings_page import PaymentMethodDialog, SettingsPage
    admin = services.auth.create_first_admin("owner", "Owner", PW)
    page = SettingsPage(services, admin)
    page.on_show()
    assert page.pm_table.rowCount() == 4
    dlg = PaymentMethodDialog(services, admin, parent=page)
    dlg.name.setText("Bank transfer")
    dlg._on_ok()
    page._load_methods()
    assert page.pm_table.rowCount() == 5
    page.pm_table.selectRow(0)   # Cash
    assert not page.pm_toggle.isEnabled()


def test_auto_print_after_sale_and_reprint(services, monkeypatch):
    import ui.dialogs.receipt_dialogs as rd
    import ui.pages.pos_page as pp
    from ui.dialogs import pos_dialogs as pd
    from ui.pages.pos_page import PosPage
    admin, cashier = _pos_setup(services)
    services.settings.update(admin, {"receipt_printer": "POS-58", "receipt_auto_print": "1"})
    printed = []
    monkeypatch.setattr(rd, "print_receipt", lambda receipt, name: printed.append((receipt, name)))
    shown = []
    monkeypatch.setattr(pp.SaleCompleteDialog, "exec", lambda self: shown.append(self) or 1)

    def fake_pay_exec(dlg):
        dlg.amount.setText("100")
        dlg._complete()
        return 1
    monkeypatch.setattr(pd.PaymentDialog, "exec", fake_pay_exec)
    page = PosPage(services, cashier)
    page.on_show()
    page.scan.setText("111")
    page.on_scan()
    page.pay()
    assert len(printed) == 1 and printed[0][1] == "POS-58" and not printed[0][0].is_reprint
    assert "Coke 290ml" in printed[0][0].plain_text()
    # "Print another copy" on the sale-complete screen = reprint
    sale_id = services.db.fetch_one("SELECT id FROM sales")["id"]
    assert rd.print_sale_receipt(page, services, cashier, sale_id)
    assert printed[1][0].is_reprint
    # printer failure does not break anything (the sale is already saved)
    def boom(*a):
        from services.errors import ServiceError
        raise ServiceError("Printer is out of paper")
    monkeypatch.setattr(rd, "print_receipt", boom)
    assert not rd.print_sale_receipt(page, services, cashier, sale_id)
    assert services.shown[-1][0] == "warning"
    assert services.db.fetch_one("SELECT COUNT(*) n FROM sales")["n"] == 1


def test_settings_receipt_printer_card(services, monkeypatch):
    import ui.printing as printing
    from ui.pages.settings_page import SettingsPage
    monkeypatch.setattr(printing, "available_printers", lambda: ["POS-58", "Office Laser"])
    admin = services.auth.create_first_admin("owner", "Owner", PW)
    page = SettingsPage(services, admin)
    page.on_show()
    assert [page.printer.itemData(i) for i in range(page.printer.count())] == ["", "POS-58", "Office Laser"]
    page.printer.setCurrentIndex(1)
    page.width_mm.setCurrentIndex(1)
    page.auto_print.setChecked(False)
    page.save()
    s = services.settings.get()
    assert (s.receipt_printer, s.receipt_width_mm, s.receipt_auto_print) == ("POS-58", 80, False)
    assert page._test_receipt().width_mm == 80


def test_inventory_pages_adjust_and_count(services, monkeypatch):
    from decimal import Decimal
    import ui.dialogs.inventory_dialogs as idl
    from ui.dialogs.inventory_dialogs import AdjustStockDialog, CountSheetDialog, MovementsDialog
    from ui.pages.inventory_page import InventoryPage
    from ui.pages.stock_count_page import NewCountDialog, StockCountPage
    admin, cashier = _pos_setup(services)
    services.settings.update(admin, {"allow_negative_stock": "0"})

    # opening stock through the count screens
    cp = StockCountPage(services, admin)
    cp.on_show()
    nd = NewCountDialog(services, admin, cp)
    nd.note.setText("Opening stock")
    nd._on_ok()
    sheet = CountSheetDialog(services, admin, nd.count_id, cp)
    assert sheet.table.rowCount() == 3
    names = [l["name"] for l in sheet.lines]
    sheet.search.setText("111")          # scanning a barcode jumps to the row
    sheet._jump()
    assert sheet.table.currentRow() == names.index("Coke 290ml") and sheet.search.text() == ""
    sheet.table.item(names.index("Coke 290ml"), sheet.COL_COUNTED).setText("24")
    sheet.table.item(names.index("Rice"), sheet.COL_COUNTED).setText("2.5")
    assert sheet.table.item(names.index("Coke 290ml"), 5).text() == "+24"
    monkeypatch.setattr(idl, "confirm", lambda *a, **k: True)
    sheet.post()
    assert not sheet.editable and not sheet.post_btn.isVisibleTo(sheet)
    cp.refresh()
    assert cp.table.item(0, 5).text() == "Finished"

    page = InventoryPage(services, admin)
    page.on_show()
    assert page.table.rowCount() == 3 and "Value" in page.cols
    row = next(i for i, r in enumerate(page.rows) if r.name == "Coke 290ml")
    assert page.table.item(row, 3).text() == "24"
    assert "Stock value (at cost): ₱265.00" in page.summary.text()   # 24x10 + 2.5x10
    page.low_only.setChecked(True)          # reorder level 0: only Coke Zero (0 in stock) is low
    assert {r.name for r in page.rows} == {"Coke Zero can"}
    page.low_only.setChecked(False)

    page.table.selectRow(row)
    dlg = AdjustStockDialog(services, admin, page.rows[row], page)
    dlg.reason.setCurrentIndex(dlg.reason.findData("damaged"))
    dlg.quantity.setText("2")
    assert "Stock after saving: 22" in dlg.preview.text()
    dlg._on_ok()
    dlg._on_ok()        # second click: same token, saved once
    assert services.inventory.available(admin, page.rows[row].product_id) == Decimal("22")
    dlg2 = AdjustStockDialog(services, admin, page.rows[row], page)
    dlg2.reason.setCurrentIndex(dlg2.reason.findData("correction"))
    assert dlg2.direction_row.isVisibleTo(dlg2)
    dlg2.quantity.setText("1")
    dlg2._on_ok()
    assert "note" in dlg2.error.text()
    page.refresh()
    m = MovementsDialog(services, admin, page.rows[row], "₱", page)
    assert m.table.rowCount() == 2 and m.table.item(0, 1).text() == "Damaged"

    # checkout refuses more than is in stock, at scan time
    from ui.pages.pos_page import PosPage
    pos = PosPage(services, cashier)
    pos.on_show()
    pos.scan.setText("23*111")
    pos.on_scan()
    assert pos.cart.is_empty and "Not enough stock" in pos.message.text()
    pos.scan.setText("22*111")
    pos.on_scan()
    assert len(pos.cart.lines) == 1
    pos.scan.setText("111")
    pos.on_scan()
    assert pos.cart.lines[0].quantity == Decimal("22")


def test_receive_page_and_suppliers(services, monkeypatch):
    from decimal import Decimal
    import ui.pages.receive_page as rp
    from ui.dialogs import pos_dialogs as pd
    from ui.pages.receive_page import COL_COST, COL_QTY, COL_TOTAL, DeliveriesDialog, ReceivePage
    from ui.pages.suppliers_page import SupplierDialog, SuppliersPage
    admin, cashier = _pos_setup(services)

    sp = SuppliersPage(services, admin)
    sp.on_show()
    dlg = SupplierDialog(services, admin, None, sp)
    dlg.name.setText("Aling Nena Wholesale")
    dlg.phone.setText("0917 111 2222")
    dlg._on_ok()
    sp.refresh()
    assert sp.table.rowCount() == 1 and sp.table.item(0, 0).text() == "Aling Nena Wholesale"

    page = ReceivePage(services, admin)
    page.on_show()
    assert page.supplier.count() == 2
    page.supplier.setCurrentIndex(1)
    page.reference.setText("DR-55")
    page.scan.setText("111")
    page.on_scan()
    page.scan.setText("111")             # scanned again: quantity 2
    page.on_scan()
    assert page.lines[0]["qty"] == "2" and page.lines[0]["cost"] == "10.00"   # current cost filled in
    page.table.item(0, COL_QTY).setText("24")
    assert page.lines[0]["total"] == "240.00"
    page.table.item(0, COL_TOTAL).setText("300")      # paid 300 for the case
    assert page.lines[0]["mode"] == "total" and page.lines[0]["cost"] == "12.50"
    monkeypatch.setattr(pd.ProductPickerDialog, "exec",
                        lambda self: (setattr(self, "chosen", [x for x in self.products if "Zero" in x.name][0]), 1)[-1])
    page.scan.setText("coke")
    page.on_scan()
    page.table.item(1, COL_QTY).setText("6")
    page.table.item(1, COL_COST).setText("45")         # more than the 38 selling price
    assert "higher than the selling price" in page.table.item(1, 6).text()
    assert "₱570.00" in page.total_label.text()
    monkeypatch.setattr(rp, "info", lambda *a, **k: None)
    page.save()
    assert not page.lines
    coke = services.products.find_by_code(admin, "111")
    assert services.inventory.available(admin, coke.id) == Decimal("24") and coke.cost_price == Decimal("12.50")
    hist = DeliveriesDialog(services, admin, "₱", page)
    assert hist.table.rowCount() == 1 and hist.table.item(0, 2).text() == "Aling Nena Wholesale"
    assert hist.table.item(0, 3).text() == "DR-55" and hist.table.item(0, 5).text() == "₱570.00"


def test_shift_screens_open_cash_expense_close(services, monkeypatch):
    from decimal import Decimal
    import ui.dialogs.shift_dialogs as sd
    import ui.pages.shift_pages as sp
    from ui.dialogs.shift_dialogs import (CashMovementDialog, CloseShiftDialog, ExpenseDialog,
                                          OpenShiftDialog, ShiftReportDialog)
    from ui.pages.pos_page import PosPage
    from ui.pages.shift_pages import ExpensesPage, MyShiftPage, ShiftsPage
    admin, cashier = _pos_setup(services)
    boss = services.auth.login("boss", "TempPass-1")
    services.shifts.close_shift(cashier, services.shifts.current(cashier)["id"], "1000")

    pos = PosPage(services, cashier)
    pos.on_show()
    assert pos.shift_banner.isVisibleTo(pos) and not pos.scan.isEnabled()

    page = MyShiftPage(services, cashier)
    page.on_show()
    assert page.status.text() == "No open shift" and page.open_btn.isVisibleTo(page)
    dlg = OpenShiftDialog(services, cashier, page)
    dlg.amount.setText("500")
    dlg._on_ok()
    page.refresh()
    assert "is open" in page.status.text() and page.close_btn.isVisibleTo(page)
    pos.on_show()
    assert not pos.shift_banner.isVisibleTo(pos) and pos.scan.isEnabled()

    # cashier: manager refuses, then approves
    monkeypatch.setattr(sd, "authorize", lambda *a, **k: None)
    cm = CashMovementDialog(services, cashier, "cash_in", page)
    cm.amount.setText("100")
    cm.reason.setText("coins")
    cm._on_ok()
    assert not cm.error.isVisibleTo(cm) and cm.result() == 0         # nothing saved, no error
    monkeypatch.setattr(sd, "authorize", lambda *a, **k: boss)
    cm._on_ok()
    ex = ExpenseDialog(services, cashier, page, drawer_only=True)
    assert ex.paid_from.count() == 1 and not ex.category.isEditable()
    ex.category.setCurrentIndex(ex.category.findText("Ice"))
    ex.amount.setText("40")
    ex._on_ok()
    page.refresh()
    assert page.moves.rowCount() == 2

    close = CloseShiftDialog(services, cashier, page.shift, "₱", page)
    close.submit()
    assert "Type the cash counted" in close.error.text()
    close.counts["500"].setValue(1)
    close.counts["50"].setValue(1)
    close.counts["5"].setValue(2)
    assert close.counted.text() == "560.00"
    close.submit()
    summary = close.result_summary
    assert summary.expected_cash == Decimal("560.00") and summary.shift["difference"] == Decimal("0.00")
    rep = ShiftReportDialog(services, cashier, summary, "₱", page)
    assert any(l.text().startswith("Exact") for l in rep.findChildren(type(page.status)))
    assert "Expected cash" in rep.report().plain_text()

    mgr = ShiftsPage(services, admin)
    mgr.on_show()
    assert mgr.table.rowCount() == 2 and "Total over/short: ₱0.00" in mgr.summary.text()

    exp = ExpensesPage(services, admin)
    exp.on_show()
    assert exp.table.rowCount() == 1
    ed = ExpenseDialog(services, admin, exp)
    assert ed.paid_from.count() == 2 and ed.category.isEditable()
    ed.category.setEditText("Internet")
    ed.amount.setText("999")
    ed.paid_from.setCurrentIndex(1)
    ed._on_ok()
    exp.refresh()
    assert exp.table.rowCount() == 2 and "₱1,039.00" in exp.summary.text()
    exp.table.selectRow(0)
    monkeypatch.setattr(sp.QInputDialog, "getText", staticmethod(lambda *a, **k: ("duplicate", True)))
    exp.void()
    assert "₱40.00" in exp.summary.text() or "₱999.00" in exp.summary.text()


def test_daily_report_page_and_dashboard(services, monkeypatch, tmp_path):
    from datetime import date, timedelta
    from openpyxl import load_workbook
    from ui.pages.dashboard_page import DashboardPage
    from ui.pages.reports_page import DailyReportPage
    from models.cart import Cart
    from services.sale_service import PaymentInput
    admin, cashier = _pos_setup(services)
    cash = next(m.id for m in services.sales.payment_methods(admin) if m.code == "CASH")
    cart = Cart()
    cart.add(services.products.find_by_code(admin, "111"), "2")
    services.sales.complete_sale(cashier, cart, [PaymentInput(cash, "100")])

    dash = DashboardPage(services, admin)
    dash.on_show()
    sales_box, sales_val = dash.tiles["sales"]
    assert sales_box.isVisibleTo(dash) and "₱40.00" in sales_val.text() and "1 sale" in sales_val.text()
    assert dash.tiles["profit"][1].text() == "₱20.00" and dash.tiles["shifts"][0].isVisibleTo(dash)
    assert not dash.tiles["my_sales"][0].isVisibleTo(dash)
    cdash = DashboardPage(services, cashier)
    cdash.on_show()
    assert "₱40.00" in cdash.tiles["my_sales"][1].text() and cdash.tiles["my_shift"][1].text() == "Open"
    assert not cdash.tiles["sales"][0].isVisibleTo(cdash) and not cdash.tiles["profit"][0].isVisibleTo(cdash)

    page = DailyReportPage(services, admin)
    page.on_show()
    texts = [page.table.item(r, 0).text() for r in range(page.table.rowCount())]
    assert "Net profit" in texts and page.stats["net_sales"].text() == "₱40.00"
    assert page.stats["net_profit"].text() == "₱20.00"
    page.day.setDate(page.day.date().addDays(-1))       # changing the day refreshes
    assert page.summary.day == date.today() - timedelta(days=1) and page.stats["net_sales"].text() == "₱0.00"
    page.day.setDate(page.day.date().addDays(1))
    saved = page.export_to(str(tmp_path / "today.xlsx"))
    assert saved and load_workbook(saved).active["A1"].value == services.settings.get().store_name
    assert services.shown[-1][0] == "information"

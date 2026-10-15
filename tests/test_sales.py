"""Completing sales: totals, payments, stock, numbering, duplicates, rollback."""
import threading
from decimal import Decimal as D

import pytest

from database.connection import DatabaseError
from models.cart import Cart, Discount
from services.errors import PermissionDenied, ValidationError
from services.product_service import ProductInput
from services.sale_service import PaymentInput

pytestmark = pytest.mark.integration


@pytest.fixture()
def shop(fresh_services):
    s = fresh_services
    admin = s.auth.create_first_admin("owner", "Owner", "Owner-Pass-1")
    roles = {r.code: r.id for r in s.users.list_roles(admin)}
    for u, role in (("cash1", "cashier"), ("boss", "manager")):
        s.users.create_user(admin, username=u, full_name=u.title(), role_id=roles[role],
                            temporary_password="TempPass-1")
    units = {u.code: u.id for u in s.catalog.list_units(admin)}
    ids = {}
    for key, name, unit, cost, price, bc in [
        ("coke", "Coke 290ml", "bottle", "15.50", "20.00", "111"),
        ("noodle", "Pancit Canton", "pack", "13.25", "17.00", "222"),
        ("rice", "Rice", "kg", "48.00", "56.00", "333")]:
        ids[key] = s.products.create(admin, ProductInput(name=name, unit_id=units[unit],
                                     cost_price=cost, selling_price=price, barcode=bc))
    methods = {m.code: m.id for m in s.sales.payment_methods(admin)}
    # These tests are about the sale itself; stock blocking has its own tests.
    s.settings.update(admin, {"allow_negative_stock": "1"})
    cashier = s.auth.login("cash1", "TempPass-1")
    boss = s.auth.login("boss", "TempPass-1")
    for who in (cashier, boss):          # selling needs an open shift
        s.shifts.open_shift(who, "500")
    return dict(s=s, admin=admin, cashier=cashier, boss=boss, ids=ids, pm=methods)


def cart_of(shop, session, *items):
    c = Cart()
    for key, qty in items:
        c.add(shop["s"].products.get(session, shop["ids"][key]), qty)
    return c


def cash(shop, amount):
    return [PaymentInput(shop["pm"]["CASH"], amount)]


def test_cash_sale_records_everything(shop):
    s, cashier = shop["s"], shop["cashier"]
    c = cart_of(shop, cashier, ("coke", "2"), ("noodle", "3"), ("rice", "0.5"))
    # 40.00 + 51.00 + 28.00 = 119.00
    r = s.sales.complete_sale(cashier, c, cash(shop, "200"))
    assert r.total == D("119.00") and r.change == D("81.00") and not r.already_saved
    assert len(r.sale_no) == 11 and r.sale_no.endswith("-0001")

    d = s.sales.sale_detail(shop["admin"], r.sale_id)
    sale, lines, pays = d["sale"], d["lines"], d["payments"]
    assert sale["cashier_id"] == cashier.user_id
    assert sale["cost_total"] == D("31.00") + D("39.75") + D("24.00")
    assert [l["quantity"] for l in lines] == [D("2.000"), D("3.000"), D("0.500")]
    assert lines[0]["unit_cost"] == D("15.50") and lines[0]["name"] == "Coke 290ml"
    assert len(pays) == 1 and pays[0]["tendered"] == D("200.00") and pays[0]["change_given"] == D("81.00")

    # stock went down (negative is allowed before stock is recorded)
    assert s.sales.stock.balance(shop["ids"]["coke"]) == D("-2.000")
    moves = s.sales.stock.movements_for("sale", r.sale_id)
    assert [m["quantity"] for m in moves] == [D("-2.000"), D("-3.000"), D("-0.500")]

    r2 = s.sales.complete_sale(cashier, cart_of(shop, cashier, ("coke", "1")), cash(shop, "20"))
    assert r2.sale_no.endswith("-0002") and r2.change == D("0.00")


def test_double_submit_returns_same_sale(shop):
    s, cashier = shop["s"], shop["cashier"]
    c = cart_of(shop, cashier, ("coke", "1"))
    r1 = s.sales.complete_sale(cashier, c, cash(shop, "50"))
    r2 = s.sales.complete_sale(cashier, c, cash(shop, "50"))
    assert r2.already_saved and r2.sale_id == r1.sale_id
    assert s.db.fetch_one("SELECT COUNT(*) n FROM sales")["n"] == 1
    assert s.sales.stock.balance(shop["ids"]["coke"]) == D("-1.000")


def test_simultaneous_submits_create_one_sale(shop):
    s, cashier = shop["s"], shop["cashier"]
    c = cart_of(shop, cashier, ("noodle", "2"))
    results, errors = [], []

    def go():
        try:
            results.append(s.sales.complete_sale(cashier, c, cash(shop, "100")))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert len({r.sale_id for r in results}) == 1
    assert s.db.fetch_one("SELECT COUNT(*) n FROM sales")["n"] == 1
    assert s.sales.stock.balance(shop["ids"]["noodle"]) == D("-2.000")


def test_split_payment_and_reference(shop):
    s, cashier, pm = shop["s"], shop["cashier"], shop["pm"]
    c = cart_of(shop, cashier, ("noodle", "6"))  # 102.00
    with pytest.raises(ValidationError, match="reference"):
        s.sales.complete_sale(cashier, c, [PaymentInput(pm["GCASH"], "50")])
    with pytest.raises(ValidationError, match="short by"):
        s.sales.complete_sale(cashier, c, [PaymentInput(pm["GCASH"], "50", "REF123")])
    with pytest.raises(ValidationError, match="more than the amount still due"):
        s.sales.complete_sale(cashier, c, [PaymentInput(pm["GCASH"], "150", "REF123")])
    r = s.sales.complete_sale(cashier, c, [PaymentInput(pm["CASH"], "100"),
                                           PaymentInput(pm["GCASH"], "50", "REF123")])
    assert r.total == D("102.00") and r.change == D("48.00") and r.amount_paid == D("150.00")
    pays = s.sales.sale_detail(shop["admin"], r.sale_id)["payments"]
    assert {(p["method"], p["amount"]) for p in pays} == {("GCash", D("50.00")), ("Cash", D("52.00"))}


def test_discounts_need_permission_and_split_correctly(shop):
    s, cashier, boss = shop["s"], shop["cashier"], shop["boss"]
    c = cart_of(shop, cashier, ("coke", "2"), ("noodle", "1"))  # 40 + 17 = 57
    c.set_sale_discount(Discount("percent", "20", "Senior citizen"))
    with pytest.raises(PermissionDenied):
        s.sales.complete_sale(cashier, c, cash(shop, "100"))
    approver = s.auth.approve("boss", "TempPass-1", "pos.discount", "20% discount", cashier)
    c.set_sale_discount(Discount("percent", "20", "Senior citizen", approver.user_id, approver.full_name))
    # a forged approval by another cashier is rejected
    c2 = cart_of(shop, cashier, ("coke", "1"))
    c2.set_line_discount(0, Discount("amount", "5", "x", approved_by=cashier.user_id + 99))
    with pytest.raises(PermissionDenied):
        s.sales.complete_sale(cashier, c2, cash(shop, "100"))

    r = s.sales.complete_sale(cashier, c, cash(shop, "50"))
    assert r.total == D("45.60")  # 57 - 11.40
    d = s.sales.sale_detail(shop["admin"], r.sale_id)
    assert d["sale"]["sale_discount"] == D("11.40")
    assert d["sale"]["sale_discount_approved_by"] == boss.user_id
    assert sum(l["sale_discount_share"] for l in d["lines"]) == D("11.40")
    assert sum(l["net_amount"] for l in d["lines"]) == D("45.60")

    # a manager can give a discount without anyone else
    c3 = cart_of(shop, boss, ("rice", "1"))
    c3.set_line_discount(0, Discount("amount", "6", "Damaged bag"))
    assert s.sales.complete_sale(boss, c3, cash(shop, "50")).total == D("50.00")


def test_failure_saves_nothing(shop, monkeypatch):
    s, cashier = shop["s"], shop["cashier"]
    c = cart_of(shop, cashier, ("coke", "1"), ("noodle", "1"))
    real = s.sales.repo.insert_payment

    def boom(*a, **k):
        raise DatabaseError("Simulated power cut", "test")
    monkeypatch.setattr(s.sales.repo, "insert_payment", boom)
    with pytest.raises(DatabaseError):
        s.sales.complete_sale(cashier, c, cash(shop, "100"))
    for table in ("sales", "sale_lines", "sale_payments", "stock_movements"):
        assert s.db.fetch_one(f"SELECT COUNT(*) n FROM {table}")["n"] == 0, table
    assert s.sales.stock.balance(shop["ids"]["coke"]) == D("0")
    # the number was not used up either: the next real sale is still -0001
    monkeypatch.setattr(s.sales.repo, "insert_payment", real)
    assert s.sales.complete_sale(cashier, c, cash(shop, "100")).sale_no.endswith("-0001")


def test_no_negative_stock_setting(shop):
    s, cashier = shop["s"], shop["cashier"]
    s.db.execute("UPDATE app_settings SET setting_value='0' WHERE setting_key='allow_negative_stock'")
    with pytest.raises(ValidationError, match="Not enough stock"):
        s.sales.complete_sale(cashier, cart_of(shop, cashier, ("coke", "1")), cash(shop, "50"))


def test_completed_sales_cannot_be_deleted(shop):
    s, cashier = shop["s"], shop["cashier"]
    s.sales.complete_sale(cashier, cart_of(shop, cashier, ("coke", "1")), cash(shop, "20"))
    for sql in ("DELETE FROM sales", "DELETE FROM sale_lines", "UPDATE sale_lines SET quantity=5",
                "DELETE FROM sale_payments", "DELETE FROM stock_movements"):
        with pytest.raises(DatabaseError):
            s.db.execute(sql)


def test_hold_recall_and_history(shop):
    s, cashier = shop["s"], shop["cashier"]
    c = cart_of(shop, cashier, ("coke", "3"))
    hid = s.sales.hold(cashier, c, "Lady in red")
    assert s.sales.held_count(cashier) == 1
    back = s.sales.recall(cashier, hid)
    assert back.totals().total == D("60.00") and s.sales.held_count(cashier) == 0
    with pytest.raises(Exception):
        s.sales.recall(cashier, hid)
    r = s.sales.complete_sale(cashier, back, cash(shop, "100"))
    from datetime import date
    rows = s.sales.search_sales(cashier, date.today(), date.today())
    assert [x["sale_no"] for x in rows] == [r.sale_no]
    assert s.sales.search_sales(shop["admin"], date.today(), date.today(), "coke")[0]["id"] == r.sale_id
    # a cashier cannot open another cashier's sale
    r2 = s.sales.complete_sale(shop["boss"], cart_of(shop, shop["boss"], ("coke", "1")), cash(shop, "20"))
    with pytest.raises(PermissionDenied):
        s.sales.sale_detail(cashier, r2.sale_id)


def test_payment_methods_admin(shop):
    s, admin = shop["s"], shop["admin"]
    mid = s.sales.save_payment_method(admin, "Bank transfer", True)
    assert "Bank transfer" in [m.name for m in s.sales.payment_methods(shop["cashier"])]
    s.sales.save_payment_method(admin, "Bank transfer", True, mid, is_active=False)
    assert "Bank transfer" not in [m.name for m in s.sales.payment_methods(shop["cashier"])]
    with pytest.raises(ValidationError, match="Cash cannot"):
        s.sales.save_payment_method(admin, "Cash", False, shop["pm"]["CASH"], is_active=False)
    with pytest.raises(PermissionDenied):
        s.sales.save_payment_method(shop["cashier"], "X", False)

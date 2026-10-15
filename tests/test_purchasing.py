"""Suppliers and receiving: stock, weighted-average cost, price history, idempotency, permissions."""
from datetime import date
from decimal import Decimal as D

import pytest

from database.connection import DatabaseError
from services.errors import PermissionDenied, ValidationError
from services.product_service import ProductInput
from services.purchasing_service import ReceiveLine

pytestmark = pytest.mark.integration


@pytest.fixture()
def store(fresh_services):
    s = fresh_services
    admin = s.auth.create_first_admin("owner", "Owner", "Owner-Pass-1")
    roles = {r.code: r.id for r in s.users.list_roles(admin)}
    for u, role in (("cash1", "cashier"), ("stock1", "inventory"), ("buyer1", "purchasing")):
        s.users.create_user(admin, username=u, full_name=u.title(), role_id=roles[role],
                            temporary_password="TempPass-1")
    units = {u.code: u.id for u in s.catalog.list_units(admin)}
    ids = {}
    for key, name, unit, cost, price, bc in [
            ("coke", "Coke 290ml", "bottle", "15.00", "20.00", "111"),
            ("rice", "Rice", "kg", "48.00", "56.00", "333")]:
        ids[key] = s.products.create(admin, ProductInput(name=name, unit_id=units[unit],
                                     cost_price=cost, selling_price=price, barcode=bc))
    login = lambda u: s.auth.login(u, "TempPass-1")  # noqa: E731
    return dict(s=s, admin=admin, ids=ids, cashier=login("cash1"), stock=login("stock1"),
                buyer=login("buyer1"))


def cost_of(s, admin, pid):
    return s.products.get(admin, pid).cost_price


def test_receive_updates_stock_cost_and_history(store):
    s, admin, ids = store["s"], store["admin"], store["ids"]
    sup = s.purchasing.save_supplier(admin, "  Puregold   Cubao ", "0917 000 0000")
    r = s.purchasing.receive(admin, [ReceiveLine(ids["coke"], "24", line_total="360"),
                                     ReceiveLine(ids["rice"], "25", unit_cost="50")],
                             supplier_id=sup, reference="DR-1001", note="weekly")
    assert r.total == D("1610.00") and r.receipt_no.startswith("RC") and r.receipt_no.endswith("-01")
    # no stock before -> the delivery cost becomes the cost
    assert s.sales.stock.balance(ids["coke"]) == D("24") and cost_of(s, admin, ids["coke"]) == D("15.00")
    assert cost_of(s, admin, ids["rice"]) == D("50.00")
    # second delivery at a higher price -> weighted average (24x15 + 12x18) / 36 = 16.00
    r2 = s.purchasing.receive(admin, [ReceiveLine(ids["coke"], "12", unit_cost="18")])
    assert r2.receipt_no.endswith("-02")
    assert s.sales.stock.balance(ids["coke"]) == D("36") and cost_of(s, admin, ids["coke"]) == D("16.00")
    hist = s.products.price_history(admin, ids["coke"])
    assert hist[0]["reason"] == f"Received {r2.receipt_no}" and hist[0]["new_cost_price"] == D("16.00")
    assert hist[0]["new_selling_price"] == D("20.00")          # selling price untouched
    # ledger
    moves = s.inventory.movements(admin, ids["coke"])
    assert [(m["movement_type"], m["quantity"], m["unit_cost"]) for m in moves] == [
        ("receive", D("12"), D("18.00")), ("receive", D("24"), D("15.00"))]
    detail = s.purchasing.receipt_detail(admin, r.receipt_id)
    assert detail["receipt"]["supplier_name"] == "Puregold Cubao"
    assert detail["receipt"]["reference"] == "DR-1001"
    l1 = detail["lines"][0]
    assert (l1["unit_cost"], l1["line_total"], l1["old_cost"], l1["new_cost"]) == (
        D("15.00"), D("360.00"), D("15.00"), D("15.00"))
    listed = s.purchasing.receipts(admin, date(2000, 1, 1), date(2100, 1, 1))
    assert [x["receipt_no"] for x in listed] == [r2.receipt_no, r.receipt_no]
    assert len(s.audit.search(admin, text="stock.received")) == 2


def test_same_product_twice_and_negative_stock(store):
    s, admin, ids = store["s"], store["admin"], store["ids"]
    s.settings.update(admin, {"allow_negative_stock": "1"})
    s.db.execute("INSERT INTO product_stock (product_id, quantity) VALUES (%s, -5)", (ids["coke"],))
    s.purchasing.receive(admin, [ReceiveLine(ids["coke"], "10", unit_cost="20"),
                                 ReceiveLine(ids["coke"], "10", unit_cost="10")])
    # below zero -> first line uses 20; then (5x20 + 10x10)/15 = 13.33
    assert s.sales.stock.balance(ids["coke"]) == D("15")
    assert cost_of(s, admin, ids["coke"]) == D("13.33")


def test_receive_is_saved_once_and_rolls_back_on_error(store):
    s, admin, ids = store["s"], store["admin"], store["ids"]
    lines = [ReceiveLine(ids["coke"], "6", unit_cost="15")]
    a = s.purchasing.receive(admin, lines, token="same-token")
    b = s.purchasing.receive(admin, lines, token="same-token")
    assert b.already_saved and b.receipt_id == a.receipt_id
    assert s.sales.stock.balance(ids["coke"]) == D("6")
    with pytest.raises(ValidationError, match="whole number"):
        s.purchasing.receive(admin, [ReceiveLine(ids["rice"], "5", unit_cost="50"),
                                     ReceiveLine(ids["coke"], "1.5", unit_cost="15")])
    assert s.sales.stock.balance(ids["rice"]) == D("0")      # nothing from the failed delivery
    assert s.db.fetch_one("SELECT COUNT(*) n FROM stock_receipts")["n"] == 1
    for bad, msg in [("0", "quantity"), ("-2", "negative"), ("abc", "valid number")]:
        with pytest.raises(ValidationError, match=msg):
            s.purchasing.receive(admin, [ReceiveLine(ids["coke"], bad, unit_cost="1")])
    with pytest.raises(ValidationError, match="Add at least one"):
        s.purchasing.receive(admin, [])
    for sql in ("DELETE FROM stock_receipts", "UPDATE stock_receipt_lines SET quantity = 1",
                "DELETE FROM stock_receipt_lines"):
        with pytest.raises(DatabaseError):
            s.db.execute(sql)


def test_zero_cost_free_goods(store):
    s, admin, ids = store["s"], store["admin"], store["ids"]
    s.purchasing.receive(admin, [ReceiveLine(ids["coke"], "10", unit_cost="15")])
    s.purchasing.receive(admin, [ReceiveLine(ids["coke"], "2", unit_cost="0")])   # freebies
    assert cost_of(s, admin, ids["coke"]) == D("12.50")      # 150 / 12


def test_suppliers_rules(store):
    s, admin = store["s"], store["admin"]
    sid = s.purchasing.save_supplier(admin, "Supplier A")
    with pytest.raises(ValidationError, match="already exists"):
        s.purchasing.save_supplier(admin, "Supplier A")
    with pytest.raises(ValidationError, match="name"):
        s.purchasing.save_supplier(admin, "   ")
    s.purchasing.save_supplier(admin, "Supplier A", "123", "", sid, is_active=False)
    assert s.purchasing.suppliers(admin) == []
    assert s.purchasing.suppliers(admin, include_inactive=True)[0]["phone"] == "123"
    with pytest.raises(ValidationError, match="not available"):
        s.purchasing.receive(admin, [ReceiveLine(store["ids"]["coke"], "1", unit_cost="1")], sid)


def test_purchasing_permissions(store):
    s, ids = store["s"], store["ids"]
    line = [ReceiveLine(ids["coke"], "1", unit_cost="15")]
    with pytest.raises(PermissionDenied):
        s.purchasing.receive(store["cashier"], line)
    with pytest.raises(PermissionDenied):
        s.purchasing.suppliers(store["cashier"])
    with pytest.raises(PermissionDenied):
        s.purchasing.save_supplier(store["stock"], "X")         # inventory staff: receive only
    s.purchasing.receive(store["stock"], line)
    s.purchasing.save_supplier(store["buyer"], "Y")
    s.purchasing.receive(store["buyer"], line)
    assert s.sales.stock.balance(ids["coke"]) == D("2")

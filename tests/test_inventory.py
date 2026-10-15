"""Inventory: costing math, adjustments, stock counts, ledger = balance, permissions, stock blocking."""
from decimal import Decimal as D

import pytest

from models.cart import Cart
from services.errors import PermissionDenied, ValidationError
from services.inventory_service import weighted_average_cost
from services.product_service import ProductInput
from services.sale_service import PaymentInput


# ------------------------------------------------------------ pure math (no DB)
@pytest.mark.parametrize("old_qty, old_cost, in_qty, in_cost, expected", [
    ("10", "10.00", "10", "12.00", "11.00"),       # equal amounts -> middle
    ("30", "10.00", "10", "14.00", "11.00"),       # (300 + 140) / 40
    ("0", "10.00", "5", "13.25", "13.25"),         # nothing left -> new cost
    ("-4", "10.00", "5", "13.25", "13.25"),        # below zero -> new cost
    ("3", "9.99", "7", "10.01", "10.00"),          # 100.04 / 10 = 10.004 -> 10.00
    ("1", "0.00", "2", "0.01", "0.01"),            # 0.02/3 = 0.0067 -> 0.01 (half up)
    ("2.5", "48.00", "0.5", "60.00", "50.00"),     # kg items
])
def test_weighted_average_cost(old_qty, old_cost, in_qty, in_cost, expected):
    assert weighted_average_cost(D(old_qty), D(old_cost), D(in_qty), D(in_cost)) == D(expected)


def test_weighted_average_needs_positive_quantity():
    with pytest.raises(ValueError):
        weighted_average_cost(D("1"), D("1"), D("0"), D("1"))


# ------------------------------------------------------------------ database
pytestmark_db = pytest.mark.integration


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
            ("coke", "Coke 290ml", "bottle", "15.50", "20.00", "111"),
            ("rice", "Rice", "kg", "48.00", "56.00", "333")]:
        ids[key] = s.products.create(admin, ProductInput(name=name, unit_id=units[unit],
                                     cost_price=cost, selling_price=price, barcode=bc,
                                     reorder_level="5"))
    login = lambda u: s.auth.login(u, "TempPass-1")  # noqa: E731
    cashier = login("cash1")
    s.shifts.open_shift(cashier, "0")
    return dict(s=s, admin=admin, ids=ids, cashier=cashier, stock=login("stock1"),
                buyer=login("buyer1"))


def opening(store, **qty):
    """Enter stock with a count (the documented way to enter opening stock)."""
    s, admin = store["s"], store["admin"]
    cid = s.inventory.start_count(admin, "Opening stock")
    s.inventory.save_counts(admin, cid, {store["ids"][k]: v for k, v in qty.items()})
    return s.inventory.post_count(admin, cid)


def ledger_matches_balance(s, product_id):
    total = D(s.inventory.repo.ledger_sum(product_id)["total"])
    return total == s.sales.stock.balance(product_id)


@pytest.mark.integration
def test_new_install_blocks_selling_without_stock(store):
    s, cashier = store["s"], store["cashier"]
    assert s.settings.get().allow_negative_stock is False
    assert s.inventory.blocks_negative_stock()
    cart = Cart()
    cart.add(s.products.get(cashier, store["ids"]["coke"]), "1")
    cash = next(m.id for m in s.sales.payment_methods(cashier) if m.is_cash)
    with pytest.raises(ValidationError, match="(?s)Not enough stock.*record it in Inventory"):
        s.sales.complete_sale(cashier, cart, [PaymentInput(cash, "20")])
    assert s.db.fetch_one("SELECT COUNT(*) n FROM sales")["n"] == 0

    opening(store, coke="12")
    r = s.sales.complete_sale(cashier, cart, [PaymentInput(cash, "20")])
    assert r.total == D("20.00")
    assert s.inventory.available(cashier, store["ids"]["coke"]) == D("11")
    assert ledger_matches_balance(s, store["ids"]["coke"])


@pytest.mark.integration
def test_opening_stock_count_and_summary(store):
    s, admin, ids = store["s"], store["admin"], store["ids"]
    res = opening(store, coke="24", rice="2.5")
    assert res == {"counted": 2, "changed": 2, "value_difference": D("372.00") + D("120.00")}
    rows = {r.sku: r for r in s.inventory.stock_list(admin)}
    coke = next(r for r in rows.values() if r.name == "Coke 290ml")
    assert coke.quantity == D("24") and coke.value == D("372.00") and not coke.is_low
    summary = s.inventory.summary(admin)
    assert summary["value"] == D("492.00") and summary["low"] == 1   # rice 2.5 <= 5
    assert [r.name for r in s.inventory.stock_list(admin, low_only=True)] == ["Rice"]
    moves = s.inventory.movements(admin, ids["coke"])
    assert moves[0]["movement_type"] == "count" and moves[0]["label"] == "Stock count"
    assert moves[0]["quantity"] == D("24") and moves[0]["balance_after"] == D("24")


@pytest.mark.integration
def test_adjustments_reasons_signs_and_double_click(store):
    s, ids, stock = store["s"], store["ids"], store["stock"]
    opening(store, coke="10")
    r = s.inventory.adjust(stock, ids["coke"], "2", "damaged", "dropped")
    assert r.new_balance == D("8")                      # damaged always removes
    r = s.inventory.adjust(stock, ids["coke"], "-1", "found")
    assert r.new_balance == D("9")                      # found always adds
    with pytest.raises(ValidationError, match="note"):
        s.inventory.adjust(stock, ids["coke"], "-1", "correction")
    r = s.inventory.adjust(stock, ids["coke"], "-1", "correction", "typed 10, was 9", token="tok-1")
    again = s.inventory.adjust(stock, ids["coke"], "-1", "correction", "typed 10, was 9", token="tok-1")
    assert again.already_saved and again.adjustment_id == r.adjustment_id and again.new_balance == D("8")
    with pytest.raises(ValidationError, match="Only 8"):
        s.inventory.adjust(stock, ids["coke"], "9", "lost")
    with pytest.raises(ValidationError, match="whole number"):
        s.inventory.adjust(stock, ids["coke"], "0.5", "lost")
    assert s.inventory.adjust(stock, ids["rice"], "0.25", "found").new_balance == D("0.25")
    with pytest.raises(ValidationError, match="reason"):
        s.inventory.adjust(stock, ids["coke"], "1", "stolen-by-aliens")
    types = [m["movement_type"] for m in s.inventory.movements(stock, ids["coke"])]
    assert types == ["adjust", "adjust", "damage", "count"]
    assert ledger_matches_balance(s, ids["coke"])
    audit = s.audit.search(store["admin"], text="stock.adjusted")
    assert len(audit) == 4


@pytest.mark.integration
def test_count_uses_stock_at_posting_time(store):
    s, ids, admin, cashier = store["s"], store["ids"], store["admin"], store["cashier"]
    opening(store, coke="20")
    cid = s.inventory.start_count(admin, "Month end")
    s.inventory.save_counts(admin, cid, {ids["coke"]: "17", ids["rice"]: ""})
    # a sale happens while the count sheet is still open
    cart = Cart()
    cart.add(s.products.get(cashier, ids["coke"]), "2")
    cash = next(m.id for m in s.sales.payment_methods(cashier) if m.is_cash)
    s.sales.complete_sale(cashier, cart, [PaymentInput(cash, "40")])
    res = s.inventory.post_count(admin, cid)
    assert res["counted"] == 1 and res["changed"] == 1
    assert s.sales.stock.balance(ids["coke"]) == D("17")   # 18 in system -> -1
    assert s.sales.stock.balance(ids["rice"]) == D("0")     # not counted: untouched
    line = next(l for l in s.inventory.get_count(admin, cid)["lines"] if l["product_id"] == ids["coke"])
    assert (line["system_qty"], line["difference"]) == (D("18"), D("-1"))
    with pytest.raises(ValidationError, match="already posted"):
        s.inventory.post_count(admin, cid)
    with pytest.raises(ValidationError, match="finished"):
        s.inventory.save_counts(admin, cid, {ids["coke"]: "1"})
    assert ledger_matches_balance(s, ids["coke"])


@pytest.mark.integration
def test_count_validation_and_cancel(store):
    s, ids, admin = store["s"], store["ids"], store["admin"]
    cid = s.inventory.start_count(admin)
    with pytest.raises(ValidationError, match="Nothing was counted"):
        s.inventory.post_count(admin, cid)
    with pytest.raises(ValidationError, match="whole number"):
        s.inventory.save_counts(admin, cid, {ids["coke"]: "1.5"})
    with pytest.raises(ValidationError, match="negative"):
        s.inventory.save_counts(admin, cid, {ids["coke"]: "-1"})
    assert s.inventory.save_counts(admin, cid, {ids["rice"]: "1.25"}) == 1
    assert s.inventory.save_counts(admin, cid, {ids["rice"]: "1.250"}) == 0   # unchanged
    s.inventory.cancel_count(admin, cid)
    with pytest.raises(ValidationError):
        s.inventory.post_count(admin, cid)
    assert s.sales.stock.balance(ids["rice"]) == D("0")
    assert [c["status"] for c in s.inventory.list_counts(admin)] == ["cancelled"]


@pytest.mark.integration
def test_inventory_permissions_and_cost_hiding(store):
    s, ids = store["s"], store["ids"]
    cashier, stock, buyer = store["cashier"], store["stock"], store["buyer"]
    with pytest.raises(PermissionDenied):
        s.inventory.stock_list(cashier)
    with pytest.raises(PermissionDenied):
        s.inventory.adjust(cashier, ids["coke"], "1", "found")
    with pytest.raises(PermissionDenied):
        s.inventory.start_count(cashier)
    assert s.inventory.available(cashier, ids["coke"]) == D("0")     # checkout may ask
    # purchasing staff: can look, cannot adjust or count, cannot see cost
    rows = s.inventory.stock_list(buyer)
    assert rows and all(r.cost_price is None and r.value is None for r in rows)
    assert "value" not in s.inventory.summary(buyer)
    with pytest.raises(PermissionDenied):
        s.inventory.adjust(buyer, ids["coke"], "1", "found")
    # inventory staff: adjust and count without approval (owner's decision)
    s.inventory.adjust(stock, ids["coke"], "3", "found")
    cid = s.inventory.start_count(stock)
    s.inventory.save_counts(stock, cid, {ids["coke"]: "2"})
    s.inventory.post_count(stock, cid)
    assert s.sales.stock.balance(ids["coke"]) == D("2")


@pytest.mark.integration
def test_movements_cannot_be_changed(store):
    from database.connection import DatabaseError
    s = store["s"]
    s.inventory.adjust(store["stock"], store["ids"]["coke"], "1", "found")
    for sql in ("UPDATE stock_adjustments SET quantity = 5", "DELETE FROM stock_adjustments"):
        with pytest.raises(DatabaseError):
            s.db.execute(sql)

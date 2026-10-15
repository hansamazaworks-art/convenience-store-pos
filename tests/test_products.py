"""Products, categories, brands, units (needs a test MySQL/MariaDB)."""
from decimal import Decimal

import pytest

from services.errors import PermissionDenied, ValidationError
from services.product_service import BelowCostWarning, ProductInput

pytestmark = pytest.mark.integration


@pytest.fixture()
def ctx(fresh_services):
    s = fresh_services
    admin = s.auth.create_first_admin("owner", "Owner", "Owner-Pass-1")
    roles = {r.code: r.id for r in s.users.list_roles(admin)}
    for u, role in (("cash1", "cashier"), ("inv1", "inventory")):
        s.users.create_user(admin, username=u, full_name=u, role_id=roles[role],
                            temporary_password="TempPass-1")
    units = {u.code: u.id for u in s.catalog.list_units(admin)}
    cats = {c.name: c.id for c in s.catalog.list_items(admin, "category")}
    return dict(s=s, admin=admin, cashier=s.auth.login("cash1", "TempPass-1"),
                inv=s.auth.login("inv1", "TempPass-1"), units=units, cats=cats)


def _input(ctx, **kw):
    base = dict(name="Coke Mismo 290ml", unit_id=ctx["units"]["bottle"], selling_price="20",
                cost_price="15.50", barcode="4801981116072", category_id=ctx["cats"]["Beverages"])
    base.update(kw)
    return ProductInput(**base)


def test_seed_data(ctx):
    assert {"pc", "kg", "pack"} <= set(ctx["units"])
    assert "Beverages" in ctx["cats"]


def test_create_search_and_scan(ctx):
    s, admin = ctx["s"], ctx["admin"]
    brand = s.catalog.save_item(admin, "brand", "Coca-Cola")
    pid = s.products.create(admin, _input(ctx, brand_id=brand))
    p = s.products.get(admin, pid)
    assert p.sku == "P000001" and p.selling_price == Decimal("20.00")
    assert p.cost_price == Decimal("15.50") and p.margin_percent == Decimal("22.50")
    s.products.create(admin, _input(ctx, name="Coke Zero 330ml", barcode="", cost_price="25",
                                    selling_price="35"))
    assert s.products.get(admin, pid + 1).sku == "P000002"

    assert [x.id for x in s.products.search(admin, "mismo")] == [pid]
    assert len(s.products.search(admin, "coke")) == 2
    assert [x.id for x in s.products.search(admin, "coca 290")] == [pid]   # brand + name words
    assert s.products.search(admin, "100%") == []
    assert s.products.find_by_code(admin, "4801981116072").id == pid
    assert s.products.find_by_code(admin, "P000001").id == pid
    assert s.products.find_by_code(admin, "nope") is None


def test_cashier_cannot_see_cost_or_edit(ctx):
    s = ctx["s"]
    pid = s.products.create(ctx["admin"], _input(ctx))
    p = s.products.get(ctx["cashier"], pid)
    assert p.cost_price is None and p.margin_percent is None and p.selling_price == Decimal("20.00")
    with pytest.raises(PermissionDenied):
        s.products.update(ctx["cashier"], pid, _input(ctx, selling_price="1"))
    with pytest.raises(PermissionDenied):
        s.catalog.save_item(ctx["cashier"], "category", "Hack")
    # inventory staff may manage products
    s.products.update(ctx["inv"], pid, _input(ctx, selling_price="21"))
    assert s.products.get(ctx["admin"], pid).selling_price == Decimal("21.00")


@pytest.mark.parametrize("field,value,msg", [
    ("name", "   ", "product name"),
    ("selling_price", "0", "more than zero"),
    ("selling_price", "abc", "not a valid amount"),
    ("selling_price", "-5", "negative"),
    ("cost_price", "-1", "negative"),
    ("selling_price", "99999999", "too large"),
    ("barcode", "48 01", "Barcode"),
    ("sku", "has space", "SKU"),
    ("unit_id", None, "unit"),
    ("reorder_level", "2.5", "whole number"),
])
def test_validation(ctx, field, value, msg):
    with pytest.raises(ValidationError, match=msg):
        ctx["s"].products.create(ctx["admin"], _input(ctx, **{field: value}))


def test_decimal_reorder_for_kg(ctx):
    pid = ctx["s"].products.create(ctx["admin"], _input(ctx, name="Rice", barcode="",
                                   unit_id=ctx["units"]["kg"], reorder_level="2.5",
                                   selling_price="52.00", cost_price="45"))
    assert ctx["s"].products.get(ctx["admin"], pid).reorder_level == Decimal("2.500")


def test_duplicates_and_below_cost(ctx):
    s, admin = ctx["s"], ctx["admin"]
    s.products.create(admin, _input(ctx, sku="COKE290"))
    with pytest.raises(ValidationError, match="already used by: Coke Mismo"):
        s.products.create(admin, _input(ctx, name="Other", sku=""))      # same barcode
    with pytest.raises(ValidationError, match="SKU 'COKE290'"):
        s.products.create(admin, _input(ctx, name="Other", barcode="", sku="coke290"))
    with pytest.raises(BelowCostWarning):
        s.products.create(admin, _input(ctx, name="Promo", barcode="", cost_price="20",
                                        selling_price="18"))
    pid = s.products.create(admin, _input(ctx, name="Promo", barcode="", cost_price="20",
                                          selling_price="18", allow_below_cost=True))
    assert s.products.get(admin, pid).margin_percent < 0


def test_price_history_audit_and_deactivate(ctx):
    s, admin = ctx["s"], ctx["admin"]
    pid = s.products.create(admin, _input(ctx))
    s.products.update(admin, pid, _input(ctx, selling_price="22", name="Coke Mismo 290 mL"))
    s.products.update(admin, pid, _input(ctx, selling_price="22", name="Coke Mismo 290 mL"))
    hist = s.products.price_history(admin, pid)
    assert len(hist) == 2  # creation + one real price change (no-op edit adds nothing)
    assert hist[0]["old_selling_price"] == Decimal("20.00")
    assert hist[0]["new_selling_price"] == Decimal("22.00")
    s.products.set_active(admin, pid, False)
    assert s.products.search(admin, "coke") == []
    assert len(s.products.search(admin, "coke", include_inactive=True)) == 1
    actions = [r["action"] for r in s.audit.search(admin, text="product")]
    assert actions.count("product.updated") == 1 and "product.deactivated" in actions


def test_catalog_lists(ctx):
    s, admin = ctx["s"], ctx["admin"]
    bid = s.catalog.save_item(admin, "brand", "  Nestlé  ")
    with pytest.raises(ValidationError, match="already exists"):
        s.catalog.save_item(admin, "brand", "nestlé")
    s.catalog.save_item(admin, "brand", "Nestle Philippines", bid, is_active=False)
    b = [x for x in s.catalog.list_items(admin, "brand") if x.id == bid][0]
    assert b.name == "Nestle Philippines" and not b.is_active
    assert all(x.id != bid for x in s.catalog.list_items(admin, "brand", include_inactive=False))
    uid = s.catalog.save_unit(admin, "dz", "Dozen", False)
    with pytest.raises(ValidationError, match="already exists"):
        s.catalog.save_unit(admin, "pc", "Something", False)
    with pytest.raises(ValidationError, match="short code"):
        s.catalog.save_unit(admin, "bad code", "X", False)
    s.catalog.save_unit(admin, "doz", "Dozen", False, uid)
    pid = s.products.create(admin, _input(ctx, unit_id=uid, barcode=""))
    assert s.products.get(admin, pid).unit_code == "doz"

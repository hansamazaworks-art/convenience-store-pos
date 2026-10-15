"""Cart arithmetic (no database needed)."""
from decimal import Decimal as D

import pytest

from models.cart import Cart, Discount, parse_quantity
from models.product import Product
from services.errors import ValidationError


def prod(pid=1, price="20.00", decimal=False, name="Item"):
    return Product(id=pid, sku=f"P{pid:06d}", barcode=None, name=name, category_id=None,
                   category_name=None, brand_id=None, brand_name=None, unit_id=1,
                   unit_code="kg" if decimal else "pc", unit_allow_decimal=decimal,
                   cost_price=None, selling_price=D(price), reorder_level=D(0),
                   track_expiry=False, is_active=True)


def test_add_merges_same_product():
    c = Cart()
    c.add(prod(1))
    c.add(prod(1), "2")
    c.add(prod(2, "5.50"))
    assert len(c.lines) == 2 and c.lines[0].quantity == D("3")
    t = c.totals()
    assert t.subtotal == D("65.50") and t.total == D("65.50") and t.item_count == D("4")


def test_quantity_rules():
    assert parse_quantity("2.5", True) == D("2.500")
    for bad, dec in [("0", False), ("-1", False), ("abc", False), ("1.5", False), ("10000", False)]:
        with pytest.raises(ValidationError):
            parse_quantity(bad, dec)
    c = Cart()
    c.add(prod(1, "52.00", decimal=True), "0.333")
    assert c.lines[0].gross == D("17.32")  # 52 x 0.333 = 17.316 -> 17.32


def test_line_and_sale_discounts():
    c = Cart()
    c.add(prod(1, "100.00"))
    c.add(prod(2, "50.00"))
    c.set_line_discount(0, Discount("percent", D("10"), "Promo"))
    assert c.totals().line_discount == D("10.00")
    c.set_sale_discount(Discount("percent", D("20"), "Senior citizen"))
    t = c.totals()
    # base after line discount = 140; 20% = 28
    assert (t.subtotal, t.line_discount, t.sale_discount, t.total) == (
        D("150.00"), D("10.00"), D("28.00"), D("112.00"))
    shares = c.sale_discount_shares()
    assert sum(shares) == D("28.00") and shares == [D("18.00"), D("10.00")]
    # quantity change re-applies the discount rules
    c.set_quantity(1, "2")
    assert c.totals().sale_discount == D("38.00")


def test_fixed_discount_never_exceeds_amount():
    c = Cart()
    c.add(prod(1, "20.00"))
    c.set_line_discount(0, Discount("amount", D("50"), "Damaged"))
    assert c.totals().total == D("0.00")


def test_discount_shares_add_up_to_cent():
    c = Cart()
    for i in range(3):
        c.add(prod(i + 1, "10.00"))
    c.set_sale_discount(Discount("amount", D("10.00"), "Promo"))
    shares = c.sale_discount_shares()
    assert sum(shares) == D("10.00") and sorted(shares) == [D("3.33"), D("3.33"), D("3.34")]


@pytest.mark.parametrize("kind,value,reason", [
    ("percent", "0", "x"), ("percent", "101", "x"), ("amount", "-1", "x"),
    ("percent", "10", "   "), ("weird", "1", "x")])
def test_bad_discounts(kind, value, reason):
    with pytest.raises(ValidationError):
        Discount(kind, value, reason)


def test_remove_and_hold_roundtrip():
    c = Cart()
    c.add(prod(1, "12.25"), "3")
    c.add(prod(2, "52.00", decimal=True), "1.5")
    c.set_line_discount(1, Discount("amount", "5", "Bulk", approved_by=7, approved_by_name="Boss"))
    c.set_sale_discount(Discount("percent", "5", "Promo"))
    restored = Cart.from_json(c.to_json())
    assert restored.totals() == c.totals()
    assert restored.token != c.token  # recalled sale = new checkout attempt
    assert restored.lines[1].discount.approved_by == 7
    c.remove(0)
    c.remove(0)
    assert c.is_empty and c.sale_discount is None
    with pytest.raises(ValidationError):
        c.remove(0)

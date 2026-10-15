"""The sale being rung up at the counter (in memory until it is completed).

All money is Decimal. Discounts are stored as a rule (percent or fixed amount)
and re-applied whenever quantities change, so a discount can never become
larger than what it applies to.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from services.errors import ValidationError
from utils.money import CENT, ZERO, to_money

MAX_LINE_QTY = Decimal("9999")
_QTY = Decimal("0.001")


def parse_quantity(raw, allow_decimal: bool) -> Decimal:
    text = str(raw).strip().replace(",", "")
    try:
        q = Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValidationError(f"'{raw}' is not a valid quantity.") from None
    if not q.is_finite() or q <= 0:
        raise ValidationError("The quantity must be more than zero.")
    if q > MAX_LINE_QTY:
        raise ValidationError(f"The quantity is too large (maximum {MAX_LINE_QTY}).")
    if not allow_decimal and q != q.to_integral_value():
        raise ValidationError("This item is sold in whole units only (no decimals).")
    return q.quantize(_QTY)


@dataclass
class Discount:
    kind: str                      # "percent" or "amount"
    value: Decimal
    reason: str
    approved_by: int | None = None  # user id of who allowed it
    approved_by_name: str = ""

    def __post_init__(self) -> None:
        if self.kind not in ("percent", "amount"):
            raise ValidationError("Unknown discount type.")
        try:
            self.value = Decimal(str(self.value))
        except InvalidOperation:
            raise ValidationError("Invalid discount value.") from None
        if not self.value.is_finite() or self.value <= 0:
            raise ValidationError("The discount must be more than zero.")
        if self.kind == "percent" and self.value > 100:
            raise ValidationError("A percentage discount cannot be more than 100%.")
        if self.kind == "amount":
            self.value = to_money(self.value)
        self.reason = " ".join((self.reason or "").split())[:100]
        if not self.reason:
            raise ValidationError("Enter the reason for the discount.")

    def amount_on(self, base: Decimal) -> Decimal:
        """Discount money for a base amount; never more than the base."""
        if base <= 0:
            return ZERO
        if self.kind == "percent":
            amt = (base * self.value / 100).quantize(CENT, rounding=ROUND_HALF_UP)
        else:
            amt = self.value
        return min(amt, base)

    def label(self, symbol: str = "") -> str:
        return f"{self.value.normalize():f}%" if self.kind == "percent" else f"{symbol}{self.value:,.2f}"


@dataclass
class CartLine:
    product_id: int
    sku: str
    barcode: str | None
    name: str
    unit_code: str
    allow_decimal: bool
    unit_price: Decimal
    quantity: Decimal
    discount: Discount | None = None

    @property
    def gross(self) -> Decimal:
        return to_money(self.unit_price * self.quantity)

    @property
    def discount_amount(self) -> Decimal:
        return self.discount.amount_on(self.gross) if self.discount else ZERO

    @property
    def net(self) -> Decimal:
        return self.gross - self.discount_amount


@dataclass(frozen=True)
class CartTotals:
    item_count: Decimal
    subtotal: Decimal
    line_discount: Decimal
    sale_discount: Decimal
    discount_total: Decimal
    total: Decimal


@dataclass
class Cart:
    lines: list[CartLine] = field(default_factory=list)
    sale_discount: Discount | None = None
    token: str = field(default_factory=lambda: str(uuid.uuid4()))

    # ----------------------------------------------------------------- edits
    def add(self, product, quantity: Decimal | str = Decimal("1")) -> int:
        """Add a product (models.product.Product). Same product again = more quantity.
        Returns the line index."""
        qty = parse_quantity(quantity, product.unit_allow_decimal)
        for i, line in enumerate(self.lines):
            if (line.product_id == product.id and line.discount is None
                    and line.unit_price == product.selling_price):
                self.set_quantity(i, line.quantity + qty)
                return i
        self.lines.append(CartLine(
            product_id=product.id, sku=product.sku, barcode=product.barcode, name=product.name,
            unit_code=product.unit_code, allow_decimal=product.unit_allow_decimal,
            unit_price=product.selling_price, quantity=qty))
        return len(self.lines) - 1

    def set_quantity(self, index: int, quantity) -> None:
        line = self._line(index)
        line.quantity = parse_quantity(quantity, line.allow_decimal)

    def remove(self, index: int) -> CartLine:
        self._line(index)
        line = self.lines.pop(index)
        if not self.lines:
            self.sale_discount = None
        return line

    def set_line_discount(self, index: int, discount: Discount | None) -> None:
        self._line(index).discount = discount

    def set_sale_discount(self, discount: Discount | None) -> None:
        if discount is not None and not self.lines:
            raise ValidationError("Add items before giving a discount.")
        self.sale_discount = discount

    def clear(self) -> None:
        self.lines.clear()
        self.sale_discount = None
        self.token = str(uuid.uuid4())

    def _line(self, index: int) -> CartLine:
        if not 0 <= index < len(self.lines):
            raise ValidationError("Select an item first.")
        return self.lines[index]

    # ---------------------------------------------------------------- totals
    @property
    def is_empty(self) -> bool:
        return not self.lines

    def totals(self) -> CartTotals:
        subtotal = sum((l.gross for l in self.lines), ZERO)
        line_disc = sum((l.discount_amount for l in self.lines), ZERO)
        base = subtotal - line_disc
        sale_disc = self.sale_discount.amount_on(base) if self.sale_discount else ZERO
        return CartTotals(
            item_count=sum((l.quantity for l in self.lines), Decimal("0")),
            subtotal=subtotal, line_discount=line_disc, sale_discount=sale_disc,
            discount_total=line_disc + sale_disc, total=subtotal - line_disc - sale_disc)

    def sale_discount_shares(self) -> list[Decimal]:
        """Split the whole-sale discount over the lines in proportion to their
        value (largest remainder, so the shares add up to the exact cent)."""
        t = self.totals()
        if t.sale_discount == 0:
            return [ZERO] * len(self.lines)
        nets = [l.net for l in self.lines]
        base = sum(nets, ZERO)
        cents_total = int(t.sale_discount * 100)
        raw = [(Decimal(cents_total) * n / base) if base else Decimal(0) for n in nets]
        floors = [int(r) for r in raw]
        leftover = cents_total - sum(floors)
        order = sorted(range(len(raw)), key=lambda i: raw[i] - floors[i], reverse=True)
        for i in order[:leftover]:
            floors[i] += 1
        shares = [Decimal(c) / 100 for c in floors]
        # a share can never exceed its line (possible only with rounding on tiny lines)
        return [min(s, n).quantize(CENT) for s, n in zip(shares, nets)]

    # ------------------------------------------------------ hold / recall
    def to_json(self) -> str:
        def enc(o):
            if isinstance(o, Decimal):
                return str(o)
            raise TypeError
        return json.dumps({"token": self.token,
                           "lines": [asdict(l) for l in self.lines],
                           "sale_discount": asdict(self.sale_discount) if self.sale_discount else None},
                          default=enc)

    @classmethod
    def from_json(cls, text: str) -> "Cart":
        data = json.loads(text)
        lines = []
        for d in data["lines"]:
            disc = Discount(**d["discount"]) if d.get("discount") else None
            d = {**d, "discount": disc, "unit_price": Decimal(d["unit_price"]),
                 "quantity": Decimal(d["quantity"])}
            lines.append(CartLine(**d))
        sd = Discount(**data["sale_discount"]) if data.get("sale_discount") else None
        # A recalled sale gets a fresh token: it is a new checkout attempt.
        return cls(lines=lines, sale_discount=sd)

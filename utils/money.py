"""Money helpers. All money is Decimal, never float.

Rounding rule: ROUND_HALF_UP to 2 decimal places (centavos), the usual
retail rule (e.g. 10.005 -> 10.01).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


class MoneyError(ValueError):
    pass


def to_money(value: object) -> Decimal:
    """Convert int/str/Decimal to a 2-decimal Decimal. Floats are rejected
    because they cannot represent centavos exactly."""
    if isinstance(value, float):
        raise MoneyError("Use Decimal or text for money, not float.")
    if isinstance(value, bool):
        raise MoneyError("Invalid money amount.")
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise MoneyError(f"'{value}' is not a valid amount.") from exc
    if not d.is_finite():
        raise MoneyError("Invalid money amount.")
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def line_total(unit_price: object, quantity: object) -> Decimal:
    qty = quantity if isinstance(quantity, Decimal) else Decimal(str(quantity))
    return to_money(to_money(unit_price) * qty)


def change_due(amount_due: object, tendered: object) -> Decimal:
    """Change to give back. Raises MoneyError if tendered is not enough."""
    due, paid = to_money(amount_due), to_money(tendered)
    if paid < due:
        raise MoneyError(f"Amount tendered is short by {format_money(due - paid)}.")
    return paid - due


def format_money(value: object, symbol: str = "₱") -> str:
    d = to_money(value)
    sign = "-" if d < 0 else ""
    return f"{sign}{symbol}{abs(d):,.2f}"

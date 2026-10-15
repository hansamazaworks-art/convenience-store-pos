"""Completing sales, sales history, held sales and payment methods.

complete_sale() is the heart of the POS. In ONE database transaction it:
  1. returns the existing sale if this cart was already completed (double-click guard),
  2. checks every discount was allowed by someone with permission,
  3. links it to the cashier's open shift (required unless switched off),
     then numbers the sale (gap-free per day),
  4. saves header, lines (with cost at time of sale), payments,
  5. deducts stock and records stock movements,
  6. writes the audit entry.
If anything fails, nothing is saved.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from database.connection import Database, DatabaseError
from models.cart import Cart, Discount
from models.user import Session
from repositories.cash_repository import CashRepository
from repositories.sale_repository import SaleRepository
from repositories.settings_repository import SettingsRepository
from repositories.stock_repository import StockRepository
from repositories.user_repository import UserRepository
from services.audit_service import AuditService
from services.errors import NotFound, PermissionDenied, ValidationError
from utils.money import ZERO, format_money, to_money

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PaymentMethod:
    id: int
    code: str
    name: str
    is_cash: bool
    requires_reference: bool
    is_active: bool


@dataclass
class PaymentInput:
    method_id: int
    tendered: Decimal | str
    reference: str = ""


@dataclass(frozen=True)
class AppliedPayment:
    method: PaymentMethod
    amount: Decimal
    tendered: Decimal
    change: Decimal
    reference: str | None


@dataclass(frozen=True)
class SaleResult:
    sale_id: int
    sale_no: str
    total: Decimal
    amount_paid: Decimal
    change: Decimal
    created_at: datetime
    already_saved: bool = False   # True when a repeated submit returned the first sale


def _pm(row: dict) -> PaymentMethod:
    return PaymentMethod(int(row["id"]), row["code"], row["name"], bool(row["is_cash"]),
                         bool(row["requires_reference"]), bool(row["is_active"]))


class SaleService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.repo = SaleRepository(db)
        self.stock = StockRepository(db)
        self.users = UserRepository(db)
        self.settings = SettingsRepository(db)
        self.cash = CashRepository(db)
        self.audit = audit or AuditService(db)

    # --------------------------------------------------- payment methods
    def payment_methods(self, session: Session, include_inactive: bool = False) -> list[PaymentMethod]:
        if include_inactive:
            session.require("settings.manage", "manage payment methods")
        else:
            session.require("pos.sell", "use the checkout")
        return [_pm(r) for r in self.repo.payment_methods(include_inactive)]

    def save_payment_method(self, session: Session, name: str, requires_reference: bool,
                            method_id: int | None = None, is_active: bool = True) -> int:
        session.require("settings.manage", "manage payment methods")
        name = " ".join((name or "").split())
        if not name or len(name) > 40:
            raise ValidationError("Enter a payment method name (up to 40 characters).")
        code = "".join(ch for ch in name.upper() if ch.isalnum())[:20] or "PM"
        with self.db.transaction() as cur:
            if method_id is None:
                if self.repo.find_payment_method(code, name, None, cur):
                    raise ValidationError(f"A payment method named '{name}' already exists.")
                method_id = self.repo.insert_payment_method(cur, code, name, requires_reference)
                self.audit.record(cur, "payment_method.created", session=session,
                                  entity_type="payment_method", entity_id=method_id,
                                  details={"name": name})
            else:
                old = self.repo.get_payment_method(method_id, cur)
                if old is None:
                    raise NotFound("This payment method no longer exists.")
                dup = self.repo.find_payment_method("\x00", name, method_id, cur)
                if dup:
                    raise ValidationError(f"A payment method named '{name}' already exists.")
                if old["is_cash"] and not is_active:
                    raise ValidationError("Cash cannot be turned off.")
                if old["is_cash"]:
                    requires_reference = False
                self.repo.update_payment_method(cur, method_id, name, requires_reference, is_active)
                self.audit.record(cur, "payment_method.updated", session=session,
                                  entity_type="payment_method", entity_id=method_id,
                                  details={"name": [old["name"], name],
                                           "active": [bool(old["is_active"]), is_active]})
        return method_id

    # -------------------------------------------------------- payments
    def apply_payments(self, total: Decimal, payments: list[PaymentInput],
                       methods: dict[int, PaymentMethod]) -> list[AppliedPayment]:
        """Turn what the customer handed over into payments that add up exactly
        to the total. Non-cash first (exact amounts), cash last (gives change)."""
        if total < 0:
            raise ValidationError("The total cannot be negative.")
        entries = []
        for p in payments:
            m = methods.get(p.method_id)
            if m is None or not m.is_active:
                raise ValidationError("That payment method is not available.")
            try:
                tendered = to_money(p.tendered)
            except Exception:  # noqa: BLE001
                raise ValidationError(f"'{p.tendered}' is not a valid amount.") from None
            if tendered <= 0:
                raise ValidationError("Payment amounts must be more than zero.")
            ref = " ".join((p.reference or "").split())[:60] or None
            if m.requires_reference and not ref:
                raise ValidationError(f"Enter the reference number for the {m.name} payment.")
            entries.append((m, tendered, ref))
        entries.sort(key=lambda e: e[0].is_cash)  # non-cash first

        remaining = total
        applied: list[AppliedPayment] = []
        for m, tendered, ref in entries:
            if remaining == 0:
                raise ValidationError("The sale is already fully paid. Remove the extra payment.")
            if m.is_cash:
                amount = min(tendered, remaining)
                applied.append(AppliedPayment(m, amount, tendered, tendered - amount, ref))
            else:
                if tendered > remaining:
                    raise ValidationError(
                        f"The {m.name} payment ({format_money(tendered, '')}) is more than the "
                        f"amount still due ({format_money(remaining, '')}).")
                applied.append(AppliedPayment(m, tendered, tendered, ZERO, ref))
            remaining -= applied[-1].amount
        if remaining > 0:
            raise ValidationError(f"The payment is short by {format_money(remaining, '')}.")
        return applied

    # ----------------------------------------------------- complete sale
    def complete_sale(self, session: Session, cart: Cart, payments: list[PaymentInput]) -> SaleResult:
        session.require("pos.sell", "complete sales")
        if cart.is_empty:
            raise ValidationError("The sale has no items.")

        existing = self.repo.find_by_token(cart.token)
        if existing:
            return self._result(existing, already=True)

        totals = cart.totals()
        methods = {m.id: m for m in self.payment_methods(session)}
        applied = self.apply_payments(totals.total, payments, methods)
        shares = cart.sale_discount_shares()
        settings = self.settings.get_all()
        allow_negative = settings.get("allow_negative_stock", "1") == "1"
        require_shift = settings.get("require_shift", "1") == "1"

        try:
            with self.db.transaction() as cur:
                if self.repo.find_by_token(cart.token, cur):  # re-check inside the transaction
                    raise _AlreadySaved()
                # Lock order everywhere: shift row first, then product rows (by id).
                shift = self.cash.open_shift_for(session.user_id, cur, lock=True)
                if shift is None and require_shift:
                    raise ValidationError("Open your shift first (count the starting cash), "
                                          "then complete the sale.")
                shift_id = int(shift["id"]) if shift else None
                self._check_discount(cur, session, cart.sale_discount)
                for line in cart.lines:
                    self._check_discount(cur, session, line.discount)

                products = self.stock.lock_products(cur, [l.product_id for l in cart.lines])
                needed: dict[int, Decimal] = {}
                for line in cart.lines:
                    if line.product_id not in products:
                        raise ValidationError(f"'{line.name}' no longer exists. Remove it from the sale.")
                    needed[line.product_id] = needed.get(line.product_id, Decimal(0)) + line.quantity
                if not allow_negative:
                    for pid, qty in needed.items():
                        have = Decimal(products[pid]["stock"])
                        if have < qty:
                            raise ValidationError(
                                f"Not enough stock for '{products[pid]['name']}': "
                                f"{have.normalize():f} in stock, {qty.normalize():f} in this sale.\n"
                                "If the shelf has more, record it in Inventory first.")

                now = self.repo.db_now(cur)
                number = self.repo.next_number(cur, "sale", now["period"])
                sale_no = f"{now['period']}-{number:04d}"

                cost_total = ZERO
                line_rows = []
                for i, (line, share) in enumerate(zip(cart.lines, shares), start=1):
                    unit_cost = Decimal(products[line.product_id]["cost_price"])
                    cost_amount = to_money(unit_cost * line.quantity)
                    cost_total += cost_amount
                    d = line.discount
                    line_rows.append(dict(
                        line_no=i, product_id=line.product_id, sku=line.sku, barcode=line.barcode,
                        name=line.name, unit_code=line.unit_code, quantity=line.quantity,
                        unit_price=line.unit_price, gross_amount=line.gross,
                        line_discount=line.discount_amount, sale_discount_share=share,
                        net_amount=line.net - share, unit_cost=unit_cost, cost_amount=cost_amount,
                        discount_reason=d.reason if d else None,
                        discount_approved_by=(d.approved_by or session.user_id) if d else None))

                amount_paid = sum((p.tendered for p in applied), ZERO)
                change = sum((p.change for p in applied), ZERO)
                sd = cart.sale_discount
                sale_id = self.repo.insert_sale(
                    cur, sale_no=sale_no, client_token=cart.token, cashier_id=session.user_id,
                    shift_id=shift_id, item_count=totals.item_count, subtotal=totals.subtotal,
                    line_discount=totals.line_discount, sale_discount=totals.sale_discount,
                    discount_total=totals.discount_total, total=totals.total,
                    amount_paid=amount_paid, change_given=change, cost_total=cost_total,
                    sale_discount_reason=sd.reason if sd else None,
                    sale_discount_approved_by=(sd.approved_by or session.user_id) if sd else None)
                for row in line_rows:
                    self.repo.insert_line(cur, sale_id=sale_id, **row)
                    self.stock.change(cur, product_id=row["product_id"], quantity=-row["quantity"],
                                      movement_type="sale", unit_cost=row["unit_cost"],
                                      reference_type="sale", reference_id=sale_id,
                                      note=sale_no, user_id=session.user_id)
                for p in applied:
                    self.repo.insert_payment(cur, sale_id, p.method.id, p.amount, p.tendered,
                                             p.change, p.reference)
                self.audit.record(cur, "sale.completed", session=session, entity_type="sale",
                                  entity_id=sale_no,
                                  details={"total": totals.total, "items": totals.item_count,
                                           "discount": totals.discount_total,
                                           "paid": ", ".join(f"{p.method.name} {p.amount}"
                                                             for p in applied)})
                created = now["now"]
        except _AlreadySaved:
            return self._result(self.repo.find_by_token(cart.token), already=True)
        except DatabaseError as exc:
            # Two submits at the very same moment: the second hits the unique token.
            if "uq_sales_token" in (exc.detail or ""):
                found = self.repo.find_by_token(cart.token)
                if found:
                    return self._result(found, already=True)
            raise
        log.info("Sale %s completed: total %s", sale_no, totals.total)
        return SaleResult(sale_id, sale_no, totals.total, amount_paid, change, created)

    def _check_discount(self, cur, session: Session, d: Discount | None) -> None:
        if d is None:
            return
        approver = d.approved_by or session.user_id
        if approver == session.user_id:
            if not session.can("pos.discount"):
                raise PermissionDenied("A manager must approve this discount.")
            return
        row = self.users.get_by_id(approver, cur)
        if (row is None or not row["is_active"]
                or "pos.discount" not in self.users.permissions_for_role(row["role_id"], cur)):
            raise PermissionDenied("The discount approval is not valid. Ask a manager again.")

    @staticmethod
    def _result(row: dict, already: bool) -> SaleResult:
        return SaleResult(int(row["id"]), row["sale_no"], Decimal(row["total"]),
                          Decimal(row["amount_paid"]), Decimal(row["change_given"]),
                          row["created_at"], already_saved=already)

    # -------------------------------------------------------- pre-sale voids
    def record_void(self, session: Session, what: str, details: dict,
                    approver: Session | None = None) -> None:
        """Log items removed / sales cancelled before payment (loss prevention)."""
        self.audit.record_now(
            "pos.line_voided" if what == "line" else "pos.sale_cancelled", session=session,
            entity_type="cart", details={**details, "approved_by": (approver or session).username})

    # ------------------------------------------------------------ held sales
    def hold(self, session: Session, cart: Cart, label: str) -> int:
        session.require("pos.sell", "hold sales")
        if cart.is_empty:
            raise ValidationError("There is nothing to hold.")
        label = " ".join((label or "").split())[:60] or datetime.now().strftime("Held %H:%M")
        t = cart.totals()
        with self.db.transaction() as cur:
            hid = self.repo.hold(cur, label, session.user_id, t.item_count, t.total, cart.to_json())
            self.audit.record(cur, "pos.sale_held", session=session, entity_type="held_sale",
                              entity_id=hid, details={"label": label, "total": t.total})
        return hid

    def held_sales(self, session: Session) -> list[dict]:
        session.require("pos.sell", "use the checkout")
        return self.repo.list_held()

    def held_count(self, session: Session) -> int:
        session.require("pos.sell", "use the checkout")
        return self.repo.count_held()

    def recall(self, session: Session, held_id: int) -> Cart:
        session.require("pos.sell", "use the checkout")
        with self.db.transaction() as cur:
            row = self.repo.take_held(cur, held_id)
            if row is None:
                raise NotFound("This held sale was already recalled.")
            self.audit.record(cur, "pos.sale_recalled", session=session, entity_type="held_sale",
                              entity_id=held_id, details={"label": row["label"]})
        return Cart.from_json(row["cart_json"])

    # --------------------------------------------------------------- history
    def search_sales(self, session: Session, date_from: date, date_to: date, text: str = "",
                     only_mine: bool = False) -> list[dict]:
        if not session.can("pos.history"):
            session.require("pos.sell", "view sales")
            only_mine = True
        return self.repo.search(date_from=date_from, date_to=date_to, text=(text or "").strip()[:60],
                                cashier_id=session.user_id if only_mine else None)

    def sale_detail(self, session: Session, sale_id: int) -> dict:
        sale = self.repo.get_sale(sale_id)
        if sale is None:
            raise NotFound("Sale not found.")
        if not session.can("pos.history") and sale["cashier_id"] != session.user_id:
            raise PermissionDenied("You can only view your own sales.")
        return {"sale": sale, "lines": self.repo.get_lines(sale_id),
                "payments": self.repo.get_payments(sale_id)}


class _AlreadySaved(Exception):
    pass

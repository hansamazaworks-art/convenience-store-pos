"""Suppliers and receiving stock.

receive() is one transaction and is idempotent by `token` (stock_receipts.client_token),
like complete_sale(). For each line it:
  1. locks the product rows (id order),
  2. recalculates the product's weighted-average cost and saves it with a price-history row,
  3. adds the stock with a 'receive' movement at the delivery's unit cost,
and writes one audit entry.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from database.connection import Database, DatabaseError
from models.user import Session
from repositories.cash_repository import CashRepository
from repositories.product_repository import ProductRepository
from repositories.purchasing_repository import PurchasingRepository
from repositories.sale_repository import SaleRepository
from repositories.stock_repository import StockRepository
from services.audit_service import AuditService
from services.errors import NotFound, PermissionDenied, ValidationError
from services.inventory_service import weighted_average_cost
from services.product_service import parse_money_field, parse_quantity_field
from services.shift_service import drawer_cash
from utils.money import ZERO, to_money

log = logging.getLogger(__name__)
MAX_LINES = 300


@dataclass
class ReceiveLine:
    """One row of the Receive stock screen (raw text from the form).
    Give either unit_cost or line_total (the amount paid for the whole line)."""
    product_id: int
    quantity: str | Decimal
    unit_cost: str | Decimal = ""
    line_total: str | Decimal = ""


@dataclass(frozen=True)
class ReceiveResult:
    receipt_id: int
    receipt_no: str
    total: Decimal
    already_saved: bool = False


def _clean(text: str | None, max_len: int) -> str | None:
    return " ".join((text or "").split())[:max_len] or None


class PurchasingService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.repo = PurchasingRepository(db)
        self.products = ProductRepository(db)
        self.stock = StockRepository(db)
        self.numbers = SaleRepository(db)
        self.cash = CashRepository(db)
        self.audit = audit or AuditService(db)

    # -------------------------------------------------------------- suppliers
    def suppliers(self, session: Session, include_inactive: bool = False) -> list[dict]:
        if not (session.can("suppliers.manage") or session.can("purchasing.receive")
                or session.can("purchasing.view")):
            raise PermissionDenied("Your account is not allowed to view suppliers.")
        return self.repo.suppliers(include_inactive)

    def save_supplier(self, session: Session, name: str, phone: str = "", note: str = "",
                      supplier_id: int | None = None, is_active: bool = True) -> int:
        session.require("suppliers.manage", "manage suppliers")
        name = _clean(name, 101)
        if not name:
            raise ValidationError("Enter the supplier name.")
        if len(name) > 100:
            raise ValidationError("The supplier name is too long (maximum 100 characters).")
        phone, note = _clean(phone, 50), _clean(note, 200)
        with self.db.transaction() as cur:
            other = self.repo.supplier_by_name(name, cur)
            if other and other["id"] != supplier_id:
                raise ValidationError(f"A supplier named '{other['name']}' already exists.")
            if supplier_id is None:
                supplier_id = self.repo.insert_supplier(cur, name, phone, note, session.user_id)
                self.audit.record(cur, "supplier.created", session=session, entity_type="supplier",
                                  entity_id=supplier_id, details={"name": name, "phone": phone})
            else:
                old = self.repo.get_supplier(supplier_id, cur)
                if old is None:
                    raise NotFound("This supplier no longer exists.")
                self.repo.update_supplier(cur, supplier_id, name, phone, note, is_active)
                changes = {k: [old[k], v] for k, v in (("name", name), ("phone", phone),
                                                       ("note", note)) if old[k] != v}
                if bool(old["is_active"]) != is_active:
                    changes["active"] = [bool(old["is_active"]), is_active]
                if changes:
                    self.audit.record(cur, "supplier.updated", session=session,
                                      entity_type="supplier", entity_id=supplier_id, details=changes)
        return supplier_id

    # ---------------------------------------------------------------- receive
    def receive(self, session: Session, lines: list[ReceiveLine], supplier_id: int | None = None,
                reference: str = "", note: str = "", token: str | None = None,
                paid_from_drawer: bool = False) -> ReceiveResult:
        """paid_from_drawer: the total was paid with cash from your open shift's drawer."""
        session.require("purchasing.receive", "receive stock")
        if not lines:
            raise ValidationError("Add at least one product to receive.")
        if len(lines) > MAX_LINES:
            raise ValidationError(f"Too many lines (maximum {MAX_LINES}). Save in two parts.")
        token = token or str(uuid.uuid4())
        reference, note = _clean(reference, 60), _clean(note, 200)

        existing = self.repo.find_by_token(token)
        if existing:
            return ReceiveResult(int(existing["id"]), existing["receipt_no"],
                                 Decimal(existing["total"]), True)
        try:
            with self.db.transaction() as cur:
                if self.repo.find_by_token(token, cur):
                    raise _AlreadySaved()
                shift = None
                if paid_from_drawer:      # lock order: shift first, then products
                    shift = self.cash.open_shift_for(session.user_id, cur, lock=True)
                    if shift is None:
                        raise ValidationError("Open your shift first to pay from the cash drawer.")
                if supplier_id:
                    sup = self.repo.get_supplier(supplier_id, cur)
                    if sup is None or not sup["is_active"]:
                        raise ValidationError("The chosen supplier is not available.")
                locked = self.stock.lock_products(cur, [int(l.product_id) for l in lines])
                clean = []
                for n, l in enumerate(lines, start=1):
                    p = locked.get(int(l.product_id))
                    if p is None:
                        raise ValidationError(f"Line {n}: this product no longer exists.")
                    info = self.products.get(int(l.product_id), cur)
                    what = f"'{info['name']}'"
                    qty = parse_quantity_field(l.quantity, f"Quantity of {what}",
                                               bool(info["unit_allow_decimal"]))
                    if qty == 0:
                        raise ValidationError(f"Enter the quantity received of {what}.")
                    if str(l.line_total).strip():
                        line_total = parse_money_field(str(l.line_total), f"Total paid for {what}", True)
                        unit_cost = to_money(line_total / qty)
                    else:
                        unit_cost = parse_money_field(str(l.unit_cost), f"Cost of {what}", True)
                        line_total = to_money(unit_cost * qty)
                    clean.append((info, qty, unit_cost, line_total))

                now = self.numbers.db_now(cur)
                number = self.numbers.next_number(cur, "receipt", now["period"])
                receipt_no = f"RC{now['period']}-{number:02d}"
                total = sum((c[3] for c in clean), ZERO)
                item_count = sum((c[1] for c in clean), Decimal(0))
                receipt_id = self.repo.insert_receipt(
                    cur, receipt_no=receipt_no, token=token, supplier_id=supplier_id or None,
                    reference=reference, note=note, item_count=item_count, total=total,
                    user_id=session.user_id)
                if shift is not None and total > 0:
                    if total > drawer_cash(self.cash, shift, cur):
                        raise ValidationError("There is not that much cash in the drawer.")
                    self.cash.insert_movement(cur, token=str(uuid.uuid4()), shift_id=int(shift["id"]),
                                              kind="purchase", amount=total,
                                              reason=f"Delivery {receipt_no}", user_id=session.user_id,
                                              reference_type="receipt", reference_id=receipt_id)

                cost_changes = {}
                for line_no, (info, qty, unit_cost, line_total) in enumerate(clean, start=1):
                    pid = int(info["id"])
                    p = locked[pid]
                    old_qty, old_cost = Decimal(p["stock"]), Decimal(p["cost_price"])
                    new_cost = weighted_average_cost(old_qty, old_cost, qty, unit_cost)
                    self.repo.insert_line(cur, receipt_id=receipt_id, line_no=line_no, product_id=pid,
                                          quantity=qty, unit_cost=unit_cost, line_total=line_total,
                                          old_cost=old_cost, new_cost=new_cost)
                    if new_cost != old_cost:
                        self._set_cost(cur, pid, old_cost, new_cost, info, session, receipt_no)
                        cost_changes[info["sku"]] = [old_cost, new_cost]
                    bal = self.stock.change(cur, product_id=pid, quantity=qty, movement_type="receive",
                                            unit_cost=unit_cost, reference_type="receipt",
                                            reference_id=receipt_id, note=receipt_no,
                                            user_id=session.user_id)
                    # keep the locked snapshot current if the same product appears again
                    p["stock"], p["cost_price"] = bal, new_cost
                self.audit.record(cur, "stock.received", session=session, entity_type="receipt",
                                  entity_id=receipt_no,
                                  details={"supplier_id": supplier_id, "reference": reference,
                                           "lines": len(clean), "total": total,
                                           "paid_from_drawer": bool(shift),
                                           "cost_changes": cost_changes or None})
        except _AlreadySaved:
            found = self.repo.find_by_token(token)
            return ReceiveResult(int(found["id"]), found["receipt_no"], Decimal(found["total"]), True)
        except DatabaseError as exc:
            if "uq_sr_token" in (exc.detail or ""):
                found = self.repo.find_by_token(token)
                if found:
                    return ReceiveResult(int(found["id"]), found["receipt_no"],
                                         Decimal(found["total"]), True)
            raise
        log.info("Stock received %s: %s lines, total %s", receipt_no, len(clean), total)
        return ReceiveResult(receipt_id, receipt_no, total)

    def _set_cost(self, cur, product_id: int, old_cost: Decimal, new_cost: Decimal, info: dict,
                  session: Session, receipt_no: str) -> None:
        self.products.set_cost(cur, product_id, new_cost, session.user_id)
        price = Decimal(info["selling_price"])
        self.products.add_price_history(cur, product_id, old_cost, new_cost, price, price,
                                        session.user_id, f"Received {receipt_no}")

    # ------------------------------------------------------------------ reads
    def receipts(self, session: Session, date_from: date, date_to: date,
                 supplier_id: int | None = None) -> list[dict]:
        if not (session.can("purchasing.receive") or session.can("purchasing.view")):
            raise PermissionDenied("Your account is not allowed to view deliveries.")
        return self.repo.search(date_from, date_to, supplier_id)

    def receipt_detail(self, session: Session, receipt_id: int) -> dict:
        if not (session.can("purchasing.receive") or session.can("purchasing.view")):
            raise PermissionDenied("Your account is not allowed to view deliveries.")
        head = self.repo.get_receipt(receipt_id)
        if head is None:
            raise NotFound("This delivery record was not found.")
        return {"receipt": head, "lines": self.repo.get_lines(receipt_id)}


class _AlreadySaved(Exception):
    pass

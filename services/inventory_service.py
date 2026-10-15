"""Inventory: stock list, movement ledger, adjustments and physical stock counts.

Every stock change goes through StockRepository.change() inside one
transaction, after locking the product rows in id order, and writes an
audit entry in the same transaction.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from database.connection import Database
from models.user import Session
from repositories.inventory_repository import InventoryRepository
from repositories.product_repository import ProductRepository
from repositories.sale_repository import SaleRepository
from repositories.settings_repository import SettingsRepository
from repositories.stock_repository import StockRepository
from services.audit_service import AuditService
from services.errors import NotFound, PermissionDenied, ValidationError
from services.product_service import ProductService, parse_quantity_field
from utils.money import ZERO, to_money

log = logging.getLogger(__name__)

# reason code: (label shown to people, stock movement type, direction: -1 out, +1 in, 0 either)
ADJUST_REASONS: dict[str, tuple[str, str, int]] = {
    "damaged": ("Damaged / spoiled", "damage", -1),
    "expired": ("Expired", "expire", -1),
    "lost": ("Lost / missing", "adjust", -1),
    "own_use": ("Store or family use", "adjust", -1),
    "found": ("Found / extra stock", "adjust", 1),
    "correction": ("Correction (wrong entry)", "adjust", 0),
}

MOVEMENT_LABELS = {
    "sale": "Sale", "receive": "Received", "adjust": "Adjustment", "damage": "Damaged",
    "expire": "Expired", "count": "Stock count", "opening": "Opening stock", "refund": "Refund",
}


def weighted_average_cost(old_qty: Decimal, old_cost: Decimal, in_qty: Decimal,
                          in_cost: Decimal) -> Decimal:
    """New average cost after receiving in_qty at in_cost.

    (old_qty x old_cost + in_qty x in_cost) / (old_qty + in_qty), rounded to
    centavos. When there was no stock (zero or negative), the incoming cost
    is used: there is nothing left to average with.
    """
    if in_qty <= 0:
        raise ValueError("in_qty must be positive")
    if old_qty <= 0:
        return to_money(in_cost)
    return to_money((old_qty * old_cost + in_qty * in_cost) / (old_qty + in_qty))


@dataclass(frozen=True)
class StockRow:
    product_id: int
    sku: str
    barcode: str | None
    name: str
    category_name: str | None
    unit_code: str
    allow_decimal: bool
    quantity: Decimal
    reorder_level: Decimal
    cost_price: Decimal | None      # None when the viewer may not see costs
    selling_price: Decimal
    is_active: bool

    @property
    def is_low(self) -> bool:
        return self.quantity <= self.reorder_level

    @property
    def value(self) -> Decimal | None:
        if self.cost_price is None:
            return None
        return to_money(max(self.quantity, Decimal(0)) * self.cost_price)


@dataclass(frozen=True)
class AdjustResult:
    adjustment_id: int
    new_balance: Decimal
    already_saved: bool = False


def _qty_text(q: Decimal) -> str:
    return f"{Decimal(q).normalize():f}"


class InventoryService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.repo = InventoryRepository(db)
        self.stock = StockRepository(db)
        self.products = ProductRepository(db)
        self.numbers = SaleRepository(db)
        self.settings = SettingsRepository(db)
        self.audit = audit or AuditService(db)

    # ----------------------------------------------------------------- reads
    def stock_list(self, session: Session, text: str = "", category_id: int | None = None,
                   low_only: bool = False, include_inactive: bool = False) -> list[StockRow]:
        session.require("inventory.view", "view stock levels")
        show = ProductService.can_see_cost(session)
        rows = self.repo.stock_list(text=(text or "").strip()[:100], category_id=category_id,
                                    low_only=low_only, include_inactive=include_inactive)
        return [StockRow(int(r["id"]), r["sku"], r["barcode"], r["name"], r["category_name"],
                         r["unit_code"], bool(r["unit_allow_decimal"]), Decimal(r["quantity"]),
                         Decimal(r["reorder_level"]),
                         Decimal(r["cost_price"]) if show else None, Decimal(r["selling_price"]),
                         bool(r["is_active"])) for r in rows]

    def summary(self, session: Session) -> dict:
        """Active products, how many are low / below zero, stock value at cost."""
        session.require("inventory.view", "view stock levels")
        t = self.repo.totals()
        out = {"products": int(t["products"]), "low": int(t["low"]), "negative": int(t["negative"])}
        if ProductService.can_see_cost(session):
            out["value"] = to_money(t["value"])
        return out

    def movements(self, session: Session, product_id: int, date_from: date | None = None,
                  date_to: date | None = None) -> list[dict]:
        session.require("inventory.view", "view stock movements")
        show = ProductService.can_see_cost(session)
        rows = self.repo.movements(product_id, date_from, date_to)
        for r in rows:
            r["label"] = MOVEMENT_LABELS.get(r["movement_type"], r["movement_type"])
            if not show:
                r["unit_cost"] = None
        return rows

    def available(self, session: Session, product_id: int) -> Decimal:
        """Quantity in stock now (the checkout uses it to warn before paying)."""
        if not (session.can("pos.sell") or session.can("inventory.view")):
            raise PermissionDenied("Your account is not allowed to view stock levels.")
        return self.stock.balance(product_id)

    def blocks_negative_stock(self) -> bool:
        return self.settings.get_all().get("allow_negative_stock", "1") != "1"

    # ----------------------------------------------------------- adjustments
    def adjust(self, session: Session, product_id: int, quantity: str | Decimal, reason: str,
               note: str = "", token: str | None = None) -> AdjustResult:
        """Add (+) or remove (-) stock for one product with a reason.

        `quantity` is signed: -3 = three pieces damaged, +2 = two found.
        The same `token` twice saves only once (double-click guard)."""
        session.require("inventory.adjust", "adjust stock")
        if reason not in ADJUST_REASONS:
            raise ValidationError("Choose a reason for the adjustment.")
        label, movement_type, direction = ADJUST_REASONS[reason]
        text = str(quantity).strip()
        negative = text.startswith("-")
        note = " ".join((note or "").split())[:200] or None
        if reason == "correction" and not note:
            raise ValidationError("Write a short note explaining the correction.")
        token = token or str(uuid.uuid4())

        with self.db.transaction() as cur:
            done = self.repo.find_adjustment(token, cur)
            if done:
                return AdjustResult(int(done["id"]), self.stock.balance(product_id, cur), True)
            product = self.products.get(product_id, cur)
            if product is None:
                raise NotFound("This product no longer exists. Refresh the list.")
            qty = parse_quantity_field(text.lstrip("+-"), "Quantity", bool(product["unit_allow_decimal"]))
            if qty == 0:
                raise ValidationError("Enter a quantity more than zero.")
            if negative:
                qty = -qty
            if direction == -1:
                qty = -abs(qty)
            elif direction == 1:
                qty = abs(qty)
            locked = self.stock.lock_products(cur, [product_id])[product_id]
            unit_cost = Decimal(locked["cost_price"])
            if qty < 0 and self.blocks_negative_stock() and Decimal(locked["stock"]) + qty < 0:
                raise ValidationError(
                    f"Only {_qty_text(locked['stock'])} {product['unit_code']} of '{product['name']}' "
                    f"in stock - you cannot remove {_qty_text(-qty)}.")
            adj_id = self.repo.insert_adjustment(cur, token=token, product_id=product_id,
                                                 quantity=qty, reason=reason, note=note,
                                                 unit_cost=unit_cost, user_id=session.user_id)
            bal = self.stock.change(cur, product_id=product_id, quantity=qty,
                                    movement_type=movement_type, unit_cost=unit_cost,
                                    reference_type="adjustment", reference_id=adj_id,
                                    note=(label + (f": {note}" if note else ""))[:200],
                                    user_id=session.user_id)
            self.audit.record(cur, "stock.adjusted", session=session, entity_type="product",
                              entity_id=product_id,
                              details={"sku": product["sku"], "name": product["name"],
                                       "quantity": qty, "reason": label, "note": note,
                                       "value": to_money(qty * unit_cost), "balance": bal})
        log.info("Stock adjusted: %s %s (%s)", product["sku"], qty, reason)
        return AdjustResult(adj_id, bal)

    # ---------------------------------------------------------- stock counts
    def list_counts(self, session: Session) -> list[dict]:
        session.require("inventory.count", "do stock counts")
        return self.repo.list_counts()

    def start_count(self, session: Session, note: str = "", category_id: int | None = None) -> int:
        """New draft count listing every active product (or one category)."""
        session.require("inventory.count", "do stock counts")
        note = " ".join((note or "").split())[:200] or None
        with self.db.transaction() as cur:
            now = self.numbers.db_now(cur)
            n = self.numbers.next_number(cur, "count", now["period"])
            count_no = f"SC{now['period']}-{n:02d}"
            count_id = self.repo.insert_count(cur, count_no, note, category_id, session.user_id)
            lines = self.repo.add_count_lines(cur, count_id, category_id)
            if not lines:
                raise ValidationError("There are no active products to count.")
            self.audit.record(cur, "stock_count.started", session=session, entity_type="stock_count",
                              entity_id=count_no, details={"products": lines, "note": note})
        return count_id

    def get_count(self, session: Session, count_id: int) -> dict:
        session.require("inventory.count", "do stock counts")
        head = self.repo.get_count(count_id)
        if head is None:
            raise NotFound("This stock count no longer exists.")
        lines = self.repo.count_lines(count_id)
        if not ProductService.can_see_cost(session):
            for l in lines:
                l["cost_price"] = l["unit_cost"] = None
        return {"count": head, "lines": lines}

    def save_counts(self, session: Session, count_id: int, counted: dict[int, str]) -> int:
        """Save typed quantities (product_id -> text; empty text = not counted yet)."""
        session.require("inventory.count", "do stock counts")
        with self.db.transaction() as cur:
            head = self.repo.get_count(count_id, cur, for_update=True)
            if head is None:
                raise NotFound("This stock count no longer exists.")
            if head["status"] != "draft":
                raise ValidationError("This count is already finished and cannot be changed.")
            lines = {int(l["product_id"]): l for l in self.repo.count_lines(count_id, cur)}
            saved = 0
            for pid, raw in counted.items():
                line = lines.get(int(pid))
                if line is None:
                    continue
                text = str(raw or "").strip()
                qty = (parse_quantity_field(text, f"Count for '{line['name']}'",
                                            bool(line["unit_allow_decimal"])) if text else None)
                old = line["counted_qty"]
                if (old is None) != (qty is None) or (qty is not None and Decimal(old) != qty):
                    self.repo.set_counted(cur, count_id, int(pid), qty)
                    saved += 1
        return saved

    def post_count(self, session: Session, count_id: int) -> dict:
        """Make the stock equal to what was counted. Products left empty are not changed.

        The difference is taken against the stock at the moment of posting, so
        sales made while counting are not counted twice."""
        session.require("inventory.count", "do stock counts")
        with self.db.transaction() as cur:
            head = self.repo.get_count(count_id, cur, for_update=True)
            if head is None:
                raise NotFound("This stock count no longer exists.")
            if head["status"] != "draft":
                raise ValidationError("This count was already posted or cancelled.")
            lines = [l for l in self.repo.count_lines(count_id, cur) if l["counted_qty"] is not None]
            if not lines:
                raise ValidationError("Nothing was counted yet. Type the counted quantities first.")
            locked = self.stock.lock_products(cur, [int(l["product_id"]) for l in lines])
            changed, value = 0, ZERO
            for l in sorted(lines, key=lambda x: int(x["product_id"])):
                p = locked[int(l["product_id"])]
                system = Decimal(p["stock"])
                diff = Decimal(l["counted_qty"]) - system
                cost = Decimal(p["cost_price"])
                self.repo.set_line_result(cur, int(l["id"]), system, diff, cost)
                if diff != 0:
                    changed += 1
                    value += to_money(diff * cost)
                    self.stock.change(cur, product_id=int(l["product_id"]), quantity=diff,
                                      movement_type="count", unit_cost=cost,
                                      reference_type="stock_count", reference_id=count_id,
                                      note=head["count_no"], user_id=session.user_id)
            self.repo.set_count_status(cur, count_id, "posted", session.user_id)
            self.audit.record(cur, "stock_count.posted", session=session, entity_type="stock_count",
                              entity_id=head["count_no"],
                              details={"counted": len(lines), "changed": changed,
                                       "value_difference": value})
        return {"counted": len(lines), "changed": changed, "value_difference": value}

    def cancel_count(self, session: Session, count_id: int) -> None:
        session.require("inventory.count", "do stock counts")
        with self.db.transaction() as cur:
            head = self.repo.get_count(count_id, cur, for_update=True)
            if head is None:
                raise NotFound("This stock count no longer exists.")
            if head["status"] != "draft":
                raise ValidationError("Only a count that is not yet posted can be cancelled.")
            self.repo.set_count_status(cur, count_id, "cancelled")
            self.audit.record(cur, "stock_count.cancelled", session=session,
                              entity_type="stock_count", entity_id=head["count_no"])

"""Products: create, edit, search, activate/deactivate, price history."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from database.connection import Database
from models.product import Product
from models.user import Session
from repositories.catalog_repository import CatalogRepository
from repositories.product_repository import ProductRepository
from services.audit_service import AuditService
from services.errors import NotFound, ValidationError
from utils.money import MoneyError, to_money

MAX_PRICE = Decimal("9999999.99")
_SKU_RE = re.compile(r"^[A-Za-z0-9._/-]{1,40}$")
_BARCODE_RE = re.compile(r"^[A-Za-z0-9-]{1,50}$")
_QTY = Decimal("0.001")


@dataclass
class ProductInput:
    """What the product form sends. Text fields are raw user input."""
    name: str
    unit_id: int | None
    selling_price: str
    cost_price: str = "0"
    sku: str = ""
    barcode: str = ""
    category_id: int | None = None
    brand_id: int | None = None
    reorder_level: str = "0"
    track_expiry: bool = False
    allow_below_cost: bool = False


@dataclass(frozen=True)
class CleanProduct:
    name: str
    sku: str
    barcode: str | None
    unit_id: int
    category_id: int | None
    brand_id: int | None
    cost_price: Decimal
    selling_price: Decimal
    reorder_level: Decimal
    track_expiry: bool


def parse_money_field(raw: str, label: str, allow_zero: bool) -> Decimal:
    try:
        value = to_money(raw if str(raw).strip() else "0")
    except MoneyError as exc:
        raise ValidationError(f"{label}: '{raw}' is not a valid amount.") from exc
    if value < 0:
        raise ValidationError(f"{label} cannot be negative.")
    if not allow_zero and value == 0:
        raise ValidationError(f"{label} must be more than zero.")
    if value > MAX_PRICE:
        raise ValidationError(f"{label} is too large.")
    return value


def parse_quantity_field(raw: str, label: str, allow_decimal: bool) -> Decimal:
    text = str(raw or "0").strip().replace(",", "") or "0"
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValidationError(f"{label}: '{raw}' is not a valid number.") from exc
    if not value.is_finite() or value < 0:
        raise ValidationError(f"{label} cannot be negative.")
    if value > Decimal("999999999"):
        raise ValidationError(f"{label} is too large.")
    if not allow_decimal and value != value.to_integral_value():
        raise ValidationError(f"{label} must be a whole number for this unit.")
    return value.quantize(_QTY)


class ProductService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.repo = ProductRepository(db)
        self.catalog = CatalogRepository(db)
        self.audit = audit or AuditService(db)

    @staticmethod
    def can_see_cost(session: Session) -> bool:
        return session.can("products.manage") or session.can("reports.financial")

    # ---------------------------------------------------------------- reads
    def search(self, session: Session, text: str = "", category_id: int | None = None,
               include_inactive: bool = False, limit: int = 500) -> list[Product]:
        session.require("products.view", "view products")
        show = self.can_see_cost(session)
        rows = self.repo.search(text=(text or "").strip()[:100], category_id=category_id,
                                include_inactive=include_inactive, limit=limit)
        return [Product.from_row(r, show) for r in rows]

    def get(self, session: Session, product_id: int) -> Product:
        session.require("products.view", "view products")
        row = self.repo.get(product_id)
        if row is None:
            raise NotFound("This product no longer exists. Refresh the list.")
        return Product.from_row(row, self.can_see_cost(session))

    def find_by_code(self, session: Session, code: str) -> Product | None:
        """Exact barcode, then exact SKU. Used by the barcode scanner."""
        session.require("products.view", "view products")
        code = (code or "").strip()
        if not code:
            return None
        row = self.repo.get_by_barcode(code) or self.repo.get_by_sku(code)
        return Product.from_row(row, self.can_see_cost(session)) if row else None

    def price_history(self, session: Session, product_id: int) -> list[dict]:
        session.require("products.manage", "view price history")
        return self.repo.price_history(product_id)

    def counts(self, session: Session) -> dict:
        session.require("products.view", "view products")
        r = self.repo.count()
        return {"total": int(r["total"]), "active": int(r["active"])}

    # --------------------------------------------------------------- writes
    def create(self, session: Session, data: ProductInput) -> int:
        session.require("products.manage", "add products")
        with self.db.transaction() as cur:
            clean = self._validate(cur, data, product_id=None)
            sku = clean.sku or f"P{self.repo.next_sku_number(cur):06d}"
            pid = self.repo.insert(cur, sku=sku, barcode=clean.barcode, name=clean.name,
                                   category_id=clean.category_id, brand_id=clean.brand_id,
                                   unit_id=clean.unit_id, cost_price=clean.cost_price,
                                   selling_price=clean.selling_price,
                                   reorder_level=clean.reorder_level,
                                   track_expiry=clean.track_expiry, user_id=session.user_id)
            self.repo.add_price_history(cur, pid, None, clean.cost_price, None,
                                        clean.selling_price, session.user_id, "New product")
            self.audit.record(cur, "product.created", session=session, entity_type="product",
                              entity_id=pid,
                              details={"sku": sku, "name": clean.name, "barcode": clean.barcode,
                                       "cost": clean.cost_price, "price": clean.selling_price})
        return pid

    def update(self, session: Session, product_id: int, data: ProductInput) -> None:
        session.require("products.manage", "edit products")
        with self.db.transaction() as cur:
            old = self.repo.get(product_id, cur, for_update=True)
            if old is None:
                raise NotFound("This product no longer exists. Refresh the list.")
            clean = self._validate(cur, data, product_id=product_id)
            sku = clean.sku or old["sku"]
            self.repo.update(cur, product_id, sku=sku, barcode=clean.barcode, name=clean.name,
                             category_id=clean.category_id, brand_id=clean.brand_id,
                             unit_id=clean.unit_id, cost_price=clean.cost_price,
                             selling_price=clean.selling_price, reorder_level=clean.reorder_level,
                             track_expiry=clean.track_expiry, user_id=session.user_id)
            old_cost, old_price = Decimal(old["cost_price"]), Decimal(old["selling_price"])
            if old_cost != clean.cost_price or old_price != clean.selling_price:
                self.repo.add_price_history(cur, product_id, old_cost, clean.cost_price, old_price,
                                            clean.selling_price, session.user_id, "Edited")
            changes = {}
            for key, before, after in [
                ("sku", old["sku"], sku), ("barcode", old["barcode"], clean.barcode),
                ("name", old["name"], clean.name), ("category", old["category_id"], clean.category_id),
                ("brand", old["brand_id"], clean.brand_id), ("unit", old["unit_id"], clean.unit_id),
                ("cost", old_cost, clean.cost_price), ("price", old_price, clean.selling_price),
                ("reorder_level", Decimal(old["reorder_level"]), clean.reorder_level),
                ("track_expiry", bool(old["track_expiry"]), clean.track_expiry),
            ]:
                if before != after:
                    changes[key] = [before, after]
            if changes:
                self.audit.record(cur, "product.updated", session=session, entity_type="product",
                                  entity_id=product_id, details={"sku": sku, **changes})

    def set_active(self, session: Session, product_id: int, active: bool) -> None:
        session.require("products.manage", "activate or deactivate products")
        with self.db.transaction() as cur:
            old = self.repo.get(product_id, cur, for_update=True)
            if old is None:
                raise NotFound("This product no longer exists. Refresh the list.")
            self.repo.set_active(cur, product_id, active, session.user_id)
            self.audit.record(cur, "product.activated" if active else "product.deactivated",
                              session=session, entity_type="product", entity_id=product_id,
                              details={"sku": old["sku"], "name": old["name"]})

    # ---------------------------------------------------------- validation
    def _validate(self, cur, d: ProductInput, product_id: int | None) -> CleanProduct:
        name = " ".join((d.name or "").split())
        if not name:
            raise ValidationError("Enter the product name.")
        if len(name) > 150:
            raise ValidationError("The product name is too long (maximum 150 characters).")

        sku = (d.sku or "").strip()
        if sku and not _SKU_RE.match(sku):
            raise ValidationError("SKU: up to 40 letters, numbers, dot, dash, slash or underscore "
                                  "(no spaces). Leave empty to create one automatically.")
        barcode = (d.barcode or "").strip() or None
        if barcode and not _BARCODE_RE.match(barcode):
            raise ValidationError("Barcode: letters, numbers and dashes only (no spaces).")

        if not d.unit_id:
            raise ValidationError("Choose the unit (e.g. Piece).")
        unit = self.catalog.get_unit(d.unit_id, cur)
        if unit is None:
            raise ValidationError("The chosen unit no longer exists.")
        for kind, item_id in (("category", d.category_id), ("brand", d.brand_id)):
            if item_id and self.catalog.get_item(kind, item_id, cur) is None:
                raise ValidationError(f"The chosen {kind} no longer exists.")

        cost = parse_money_field(d.cost_price, "Cost price", allow_zero=True)
        price = parse_money_field(d.selling_price, "Selling price", allow_zero=False)
        if price < cost and not d.allow_below_cost:
            raise BelowCostWarning(cost, price)
        reorder = parse_quantity_field(d.reorder_level, "Reorder level", bool(unit["allow_decimal"]))

        if sku:
            other = self.repo.get_by_sku(sku, cur)
            if other and other["id"] != product_id:
                raise ValidationError(f"SKU '{other['sku']}' is already used by: {other['name']}.")
        if barcode:
            other = self.repo.get_by_barcode(barcode, cur)
            if other and other["id"] != product_id:
                raise ValidationError(f"Barcode {barcode} is already used by: {other['name']}.")

        return CleanProduct(name=name, sku=sku, barcode=barcode, unit_id=int(d.unit_id),
                            category_id=d.category_id or None, brand_id=d.brand_id or None,
                            cost_price=cost, selling_price=price, reorder_level=reorder,
                            track_expiry=bool(d.track_expiry))


class BelowCostWarning(ValidationError):
    """Selling price is lower than cost. The form asks the user to confirm."""

    def __init__(self, cost: Decimal, price: Decimal) -> None:
        super().__init__(f"The selling price ({price}) is lower than the cost ({cost}). "
                         "The store would lose money on every sale.")
        self.cost, self.price = cost, price

"""Product catalog data objects."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CatalogItem:
    """A category or a brand."""
    id: int
    name: str
    is_active: bool
    product_count: int = 0


@dataclass(frozen=True)
class Unit:
    id: int
    code: str
    name: str
    allow_decimal: bool
    is_active: bool
    product_count: int = 0


@dataclass(frozen=True)
class Product:
    id: int
    sku: str
    barcode: str | None
    name: str
    category_id: int | None
    category_name: str | None
    brand_id: int | None
    brand_name: str | None
    unit_id: int
    unit_code: str
    unit_allow_decimal: bool
    cost_price: Decimal | None      # None when the viewer may not see costs
    selling_price: Decimal
    reorder_level: Decimal
    track_expiry: bool
    is_active: bool

    @property
    def margin_percent(self) -> Decimal | None:
        """Gross margin on the selling price, e.g. 25.00 (%)."""
        if self.cost_price is None or not self.selling_price:
            return None
        return ((self.selling_price - self.cost_price) / self.selling_price * 100).quantize(
            Decimal("0.01"))

    @classmethod
    def from_row(cls, r: dict, show_cost: bool = True) -> "Product":
        return cls(
            id=int(r["id"]), sku=r["sku"], barcode=r["barcode"], name=r["name"],
            category_id=r["category_id"], category_name=r.get("category_name"),
            brand_id=r["brand_id"], brand_name=r.get("brand_name"),
            unit_id=int(r["unit_id"]), unit_code=r["unit_code"],
            unit_allow_decimal=bool(r["unit_allow_decimal"]),
            cost_price=Decimal(r["cost_price"]) if show_cost else None,
            selling_price=Decimal(r["selling_price"]),
            reorder_level=Decimal(r["reorder_level"]),
            track_expiry=bool(r["track_expiry"]), is_active=bool(r["is_active"]),
        )

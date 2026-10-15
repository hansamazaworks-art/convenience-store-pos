"""Categories, brands and units."""
from __future__ import annotations

import re

from database.connection import Database
from models.product import CatalogItem, Unit
from models.user import Session
from repositories.catalog_repository import CatalogRepository
from services.audit_service import AuditService
from services.errors import NotFound, ValidationError

_LABEL = {"category": "category", "brand": "brand"}
_UNIT_CODE_RE = re.compile(r"^[A-Za-z0-9.]{1,10}$")


def _clean_name(name: str, what: str, max_len: int = 80) -> str:
    n = " ".join((name or "").split())
    if not n:
        raise ValidationError(f"Enter the {what} name.")
    if len(n) > max_len:
        raise ValidationError(f"The {what} name is too long (maximum {max_len} characters).")
    return n


class CatalogService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.repo = CatalogRepository(db)
        self.audit = audit or AuditService(db)

    # ------------------------------------------------- categories / brands
    def list_items(self, session: Session, kind: str, include_inactive: bool = True) -> list[CatalogItem]:
        session.require("products.view", "view products")
        return [CatalogItem(int(r["id"]), r["name"], bool(r["is_active"]), int(r["product_count"]))
                for r in self.repo.list_items(kind, include_inactive)]

    def save_item(self, session: Session, kind: str, name: str, item_id: int | None = None,
                  is_active: bool = True) -> int:
        what = _LABEL[kind]
        session.require("products.manage", f"change {what} list")
        name = _clean_name(name, what)
        with self.db.transaction() as cur:
            dup = self.repo.find_item_by_name(kind, name, cur)
            if dup and dup["id"] != item_id:
                raise ValidationError(f"A {what} named '{dup['name']}' already exists.")
            if item_id is None:
                item_id = self.repo.insert_item(cur, kind, name)
                self.audit.record(cur, f"{kind}.created", session=session, entity_type=kind,
                                  entity_id=item_id, details={"name": name})
            else:
                old = self.repo.get_item(kind, item_id, cur, for_update=True)
                if old is None:
                    raise NotFound(f"This {what} no longer exists. Refresh the list.")
                self.repo.update_item(cur, kind, item_id, name, is_active)
                self.audit.record(cur, f"{kind}.updated", session=session, entity_type=kind,
                                  entity_id=item_id,
                                  details={"name": [old["name"], name],
                                           "active": [bool(old["is_active"]), is_active]})
        return item_id

    # --------------------------------------------------------------- units
    def list_units(self, session: Session, include_inactive: bool = True) -> list[Unit]:
        session.require("products.view", "view products")
        return [Unit(int(r["id"]), r["code"], r["name"], bool(r["allow_decimal"]),
                     bool(r["is_active"]), int(r["product_count"]))
                for r in self.repo.list_units(include_inactive)]

    def save_unit(self, session: Session, code: str, name: str, allow_decimal: bool,
                  unit_id: int | None = None, is_active: bool = True) -> int:
        session.require("products.manage", "change units")
        code = (code or "").strip()
        if not _UNIT_CODE_RE.match(code):
            raise ValidationError("Unit short code: 1 to 10 letters or numbers, e.g. pc, kg, pack.")
        name = _clean_name(name, "unit", 40)
        with self.db.transaction() as cur:
            dup = self.repo.find_unit(code, name, unit_id, cur)
            if dup:
                raise ValidationError(f"A unit with this code or name already exists "
                                      f"({dup['code']} - {dup['name']}).")
            if unit_id is None:
                unit_id = self.repo.insert_unit(cur, code, name, allow_decimal)
                self.audit.record(cur, "unit.created", session=session, entity_type="unit",
                                  entity_id=unit_id, details={"code": code, "name": name})
            else:
                old = self.repo.get_unit(unit_id, cur, for_update=True)
                if old is None:
                    raise NotFound("This unit no longer exists. Refresh the list.")
                self.repo.update_unit(cur, unit_id, code, name, allow_decimal, is_active)
                self.audit.record(cur, "unit.updated", session=session, entity_type="unit",
                                  entity_id=unit_id,
                                  details={"code": [old["code"], code], "name": [old["name"], name],
                                           "decimal": [bool(old["allow_decimal"]), allow_decimal],
                                           "active": [bool(old["is_active"]), is_active]})
        return unit_id

"""Store-wide settings (name, currency, receipt footer)."""
from __future__ import annotations

from dataclasses import dataclass

from database.connection import Database
from models.user import Session
from repositories.settings_repository import SettingsRepository
from services.audit_service import AuditService
from services.errors import ValidationError


@dataclass(frozen=True)
class StoreSettings:
    store_name: str
    currency_symbol: str
    receipt_footer: str
    store_address: str
    store_phone: str
    tax_id: str
    costing_method: str
    receipt_printer: str = ""
    receipt_width_mm: int = 58
    receipt_auto_print: bool = True
    receipt_note: str = ""
    allow_negative_stock: bool = False


_FIELDS = {
    # key: (label, max length, required)
    "store_name": ("Store name", 100, True),
    "store_address": ("Address", 200, False),
    "store_phone": ("Phone", 50, False),
    "tax_id": ("Tax / business ID", 50, False),
    "currency_symbol": ("Currency symbol", 5, True),
    "receipt_footer": ("Receipt footer", 200, False),
    "receipt_note": ("Receipt note", 200, False),
    "receipt_printer": ("Receipt printer", 200, False),
    "receipt_width_mm": ("Paper width", 2, True),
    "receipt_auto_print": ("Print automatically", 1, True),
    "allow_negative_stock": ("Sell without stock", 1, True),
}
_CHOICES = {"receipt_width_mm": {"58", "80"}, "receipt_auto_print": {"0", "1"},
            "allow_negative_stock": {"0", "1"}}
_KEEP_SPACES = {"receipt_printer"}  # printer names must match Windows exactly


class SettingsService:
    def __init__(self, db: Database, audit: AuditService | None = None,
                 defaults: dict[str, str] | None = None) -> None:
        self.db = db
        self.repo = SettingsRepository(db)
        self.audit = audit or AuditService(db)
        self.defaults = defaults or {}

    def get(self) -> StoreSettings:
        v = {**self.defaults, **self.repo.get_all()}
        return StoreSettings(
            store_name=v.get("store_name", "My Convenience Store"),
            currency_symbol=v.get("currency_symbol", "₱"),
            receipt_footer=v.get("receipt_footer", ""),
            store_address=v.get("store_address", ""),
            store_phone=v.get("store_phone", ""),
            tax_id=v.get("tax_id", ""),
            costing_method=v.get("inventory_costing_method", "WEIGHTED_AVERAGE"),
            receipt_printer=v.get("receipt_printer", ""),
            receipt_width_mm=80 if v.get("receipt_width_mm") == "80" else 58,
            receipt_auto_print=v.get("receipt_auto_print", "1") == "1",
            receipt_note=v.get("receipt_note", ""),
            allow_negative_stock=v.get("allow_negative_stock", "1") == "1",
        )

    def update(self, session: Session, values: dict[str, str]) -> StoreSettings:
        session.require("settings.manage", "change store settings")
        clean: dict[str, str] = {}
        for key, raw in values.items():
            if key not in _FIELDS:
                raise ValidationError(f"Unknown setting: {key}")
            label, max_len, required = _FIELDS[key]
            val = str(raw or "").strip() if key in _KEEP_SPACES else " ".join(str(raw or "").split())
            if key in _CHOICES and val not in _CHOICES[key]:
                raise ValidationError(f"{label}: choose one of {', '.join(sorted(_CHOICES[key]))}.")
            if required and not val:
                raise ValidationError(f"{label} cannot be empty.")
            if len(val) > max_len:
                raise ValidationError(f"{label} is too long (maximum {max_len} characters).")
            clean[key] = val
        with self.db.transaction() as cur:
            before = self.repo.get_all(cur)
            changed = {k: [before.get(k, ""), v] for k, v in clean.items() if before.get(k, "") != v}
            for k, v in clean.items():
                self.repo.upsert(cur, k, v)
            if changed:
                self.audit.record(cur, "settings.updated", session=session,
                                  entity_type="settings", details=changed)
        return self.get()

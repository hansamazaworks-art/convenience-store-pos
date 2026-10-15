"""Creates every service once, so screens share the same instances."""
from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings, app_root
from database.connection import Database
from services.audit_service import AuditService
from services.auth_service import AuthService
from services.backup_service import BackupService
from services.catalog_service import CatalogService
from services.expense_service import ExpenseService
from services.inventory_service import InventoryService
from services.product_service import ProductService
from services.purchasing_service import PurchasingService
from services.receipt_service import ReceiptService
from services.report_service import ReportService
from services.sale_service import SaleService
from services.settings_service import SettingsService
from services.shift_service import ShiftService
from services.system_service import SystemService
from services.user_service import UserService


@dataclass
class Services:
    db: Database
    system: SystemService
    audit: AuditService
    auth: AuthService
    users: UserService
    settings: SettingsService
    catalog: CatalogService
    products: ProductService
    sales: SaleService
    receipts: ReceiptService
    inventory: InventoryService
    purchasing: PurchasingService
    shifts: ShiftService
    expenses: ExpenseService
    reports: ReportService
    backups: BackupService

    @classmethod
    def build(cls, db: Database, app_settings: Settings | None = None) -> "Services":
        audit = AuditService(db)
        defaults = {}
        if app_settings is not None:
            defaults = {"store_name": app_settings.store_name,
                        "currency_symbol": app_settings.currency_symbol}
        settings = SettingsService(db, audit, defaults)
        sales = SaleService(db, audit)
        return cls(
            db=db,
            system=SystemService(db),
            audit=audit,
            auth=AuthService(db, audit),
            users=UserService(db, audit),
            settings=settings,
            catalog=CatalogService(db, audit),
            products=ProductService(db, audit),
            sales=sales,
            receipts=ReceiptService(db, sales, settings, audit),
            inventory=InventoryService(db, audit),
            purchasing=PurchasingService(db, audit),
            shifts=ShiftService(db, audit),
            expenses=ExpenseService(db, audit),
            reports=ReportService(db),
            backups=BackupService(db.cfg, app_settings.backup_dir if app_settings else app_root() / "backups",
                                  app_settings.mysql_bin_dir if app_settings else None),
        )

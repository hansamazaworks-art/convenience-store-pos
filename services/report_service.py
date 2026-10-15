"""Dashboard numbers and the daily summary report (read-only).

Everything is computed from the saved records, so the report always agrees with
Sales history, the shifts and the expenses:

    net sales    = sum of sales.total (after discounts) for the day
    gross profit = net sales - cost of the items sold (sales.cost_total, cost at time of sale)
    net profit   = gross profit - expenses of the day (voided expenses not counted)

Cost and profit are shown only to roles that may see cost (ProductService.can_see_cost).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from database.connection import Database
from models.user import Session
from repositories.cash_repository import CashRepository
from repositories.inventory_repository import InventoryRepository
from repositories.report_repository import ReportRepository
from services.product_service import ProductService
from utils.money import ZERO, to_money


@dataclass(frozen=True)
class DailySummary:
    day: date
    sales_count: int
    items: Decimal
    gross: Decimal              # before discounts
    discounts: Decimal
    net_sales: Decimal          # what customers paid
    cost: Decimal | None        # None = this user may not see cost
    payments: list[dict]        # name, is_cash, amount, n
    expenses: list[dict]        # category, paid_from, amount, n
    deliveries_count: int
    deliveries_total: Decimal | None
    shifts: list[dict] = field(default_factory=list)

    @property
    def cash_sales(self) -> Decimal:
        return to_money(sum((Decimal(p["amount"]) for p in self.payments if p["is_cash"]), ZERO))

    @property
    def expenses_total(self) -> Decimal:
        return to_money(sum((Decimal(e["amount"]) for e in self.expenses), ZERO))

    @property
    def gross_profit(self) -> Decimal | None:
        return None if self.cost is None else to_money(self.net_sales - self.cost)

    @property
    def net_profit(self) -> Decimal | None:
        gp = self.gross_profit
        return None if gp is None else to_money(gp - self.expenses_total)

    @property
    def over_short(self) -> Decimal:
        """Total over (+) / short (-) of the closed shifts that started this day."""
        return to_money(sum((Decimal(s["difference"]) for s in self.shifts
                             if s["difference"] is not None), ZERO))


class ReportService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.repo = ReportRepository(db)
        self.cash = CashRepository(db)
        self.inventory = InventoryRepository(db)

    def daily_summary(self, session: Session, day: date) -> DailySummary:
        session.require("reports.sales", "see the daily report")
        show_cost = ProductService.can_see_cost(session)
        t = self.repo.sales_totals(day)
        d = self.repo.deliveries(day)
        return DailySummary(
            day=day, sales_count=int(t["n"]), items=Decimal(t["items"]),
            gross=to_money(t["gross"]), discounts=to_money(t["discounts"]),
            net_sales=to_money(t["total"]), cost=to_money(t["cost"]) if show_cost else None,
            payments=self.repo.payments_by_method(day), expenses=self.repo.expenses_by_category(day),
            deliveries_count=int(d["n"]), deliveries_total=to_money(d["total"]) if show_cost else None,
            shifts=self.cash.list_shifts(day, day))

    def dashboard(self, session: Session, day: date) -> dict:
        """Only the numbers this user is allowed to see; missing keys are not shown."""
        out: dict = {}
        if session.can("reports.sales"):
            t = self.repo.sales_totals(day)
            out["sales_count"], out["sales_total"] = int(t["n"]), to_money(t["total"])
            if ProductService.can_see_cost(session):
                out["gross_profit"] = to_money(Decimal(t["total"]) - Decimal(t["cost"]))
        elif session.can("pos.sell"):
            t = self.repo.sales_totals(day, cashier_id=session.user_id)
            out["my_sales_count"], out["my_sales_total"] = int(t["n"]), to_money(t["total"])
        if session.can("inventory.view"):
            tot = self.inventory.totals()
            out["low_stock"], out["negative_stock"] = int(tot["low"]), int(tot["negative"])
        if session.can("shifts.manage"):
            out["open_shifts"] = [s["user_name"] for s in self.cash.open_shifts()]
        elif session.can("shifts.own"):
            out["my_shift_open"] = self.cash.open_shift_for(session.user_id) is not None
        return out


@dataclass(frozen=True)
class Line:
    """One line of the daily summary as shown on screen and in Excel."""
    label: str
    value: Decimal | int | str | None = None   # Decimal = money; None = section heading
    bold: bool = False

    @property
    def is_heading(self) -> bool:
        return self.value is None


def summary_lines(s: DailySummary) -> list[Line]:
    out = [Line("SALES"), Line("Number of sales", s.sales_count), Line("Items sold", f"{s.items.normalize():f}"),
           Line("Sales before discounts", s.gross), Line("Discounts", -s.discounts),
           Line("Net sales", s.net_sales, True), Line("PAYMENTS")]
    out += [Line(f"{p['name']} ({p['n']})", to_money(p["amount"])) for p in s.payments]
    if s.cost is not None:
        out += [Line("PROFIT"), Line("Net sales", s.net_sales), Line("Cost of items sold", -s.cost),
                Line("Gross profit", s.gross_profit, True), Line("Expenses", -s.expenses_total),
                Line("Net profit", s.net_profit, True)]
    out.append(Line("EXPENSES"))
    out += [Line(f"{e['category']} ({'drawer' if e['paid_from'] == 'drawer' else 'other money'})",
                 to_money(e["amount"])) for e in s.expenses]
    out += [Line("Total expenses", s.expenses_total, True),
            Line("CASH DRAWER (shifts started this day)"), Line("Cash sales", s.cash_sales)]
    for sh in s.shifts:
        name = f"Shift {sh['shift_no']} – {sh['user_name']}"
        out.append(Line(name, "still open") if sh["status"] == "open"
                   else Line(f"{name}: over (+) / short (−)", to_money(sh["difference"])))
    out.append(Line("Total over / short", s.over_short, True))
    if s.deliveries_total is not None:
        out += [Line("STOCK BOUGHT"), Line(f"Deliveries received ({s.deliveries_count})", s.deliveries_total)]
    return out

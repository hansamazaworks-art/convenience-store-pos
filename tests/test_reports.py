"""Dashboard numbers and the daily summary report reconcile with the saved records."""
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from openpyxl import load_workbook

from reports.excel import save_daily_summary
from services.errors import PermissionDenied
from services.report_service import summary_lines
from tests.test_shifts import sell, shop  # noqa: F401  (fixture)
from services.sale_service import PaymentInput

pytestmark = pytest.mark.integration


def _day_of_trading(shop):
    """Cashier: float 500, 2 cash sales (100), 1 GCash sale (50), ice 40 from the drawer,
    counts 550 (10 short). Owner: rent 300 from other money, one voided expense."""
    s, cashier, boss, admin, pm = shop["s"], shop["cashier"], shop["boss"], shop["admin"], shop["pm"]
    cats = {c["name"]: c["id"] for c in s.expenses.categories(admin)}
    sid = s.shifts.open_shift(cashier, "500")
    sell(shop, cashier, "2", [PaymentInput(pm["CASH"], "200")])
    sell(shop, cashier, "1", [PaymentInput(pm["GCASH"], "50", "REF123")])
    s.expenses.add(cashier, category=cats["Ice"], amount="40", approved_by=boss.user_id)
    s.expenses.add(admin, category=cats["Rent"], amount="300", paid_from="other")
    void_id = s.expenses.add(admin, category=cats["Water"], amount="99", paid_from="other")
    s.expenses.void(admin, void_id, "typed twice")
    s.shifts.close_shift(cashier, sid, "550")
    return sid


def test_daily_summary_reconciles_with_records(shop):
    s, admin = shop["s"], shop["admin"]
    _day_of_trading(shop)
    r = s.reports.daily_summary(admin, date.today())
    assert (r.sales_count, r.items, r.gross, r.discounts, r.net_sales) == (2, D("3"), D("150.00"),
                                                                         D("0.00"), D("150.00"))
    # the same numbers straight from the tables
    db = s.db.fetch_one("SELECT SUM(total) AS t, SUM(cost_total) AS c FROM sales "
                        "WHERE DATE(created_at) = CURDATE()")
    paid = s.db.fetch_one("SELECT SUM(p.amount) AS a FROM sale_payments p JOIN sales x ON x.id = p.sale_id "
                          "WHERE DATE(x.created_at) = CURDATE()")
    assert r.net_sales == db["t"] == paid["a"] == sum(D(p["amount"]) for p in r.payments)
    assert r.cost == db["c"] == D("60.00") and r.gross_profit == D("90.00")
    assert r.cash_sales == D("100.00")
    assert r.expenses_total == D("340.00")            # voided expense not counted
    assert r.net_profit == D("-250.00")
    assert r.over_short == D("-10.00") and len(r.shifts) == 1
    assert r.deliveries_count == 1 and r.deliveries_total == D("2000.00")
    labels = [ln.label for ln in summary_lines(r)]
    assert "Net profit" in labels and "Ice (drawer)" in labels and "Rent (other money)" in labels

    empty = s.reports.daily_summary(admin, date.today() - timedelta(days=1))
    assert (empty.sales_count, empty.net_sales, empty.net_profit, empty.payments) == (0, D("0.00"),
                                                                                    D("0.00"), [])


def test_report_permissions_and_hidden_cost(shop):
    s, cashier, boss = shop["s"], shop["cashier"], shop["boss"]
    _day_of_trading(shop)
    with pytest.raises(PermissionDenied):
        s.reports.daily_summary(cashier, date.today())
    no_cost = replace(boss, permissions=boss.permissions - {"reports.financial", "products.manage"})
    r = s.reports.daily_summary(no_cost, date.today())
    assert r.cost is None and r.gross_profit is None and r.deliveries_total is None
    labels = [ln.label for ln in summary_lines(r)]
    assert "PROFIT" not in labels and "Gross profit" not in labels


def test_dashboard_per_role(shop):
    s, cashier, boss = shop["s"], shop["cashier"], shop["boss"]
    _day_of_trading(shop)
    s.shifts.open_shift(shop["cashier2"], "100")
    d = s.reports.dashboard(boss, date.today())
    assert d["sales_total"] == D("150.00") and d["sales_count"] == 2 and d["gross_profit"] == D("90.00")
    assert d["open_shifts"] == ["Cash2"] and "low_stock" in d and "my_sales_total" not in d
    c = s.reports.dashboard(cashier, date.today())
    assert c == {"my_sales_count": 2, "my_sales_total": D("150.00"), "my_shift_open": False}
    c2 = s.reports.dashboard(shop["cashier2"], date.today())
    assert c2["my_sales_count"] == 0 and c2["my_shift_open"] is True


def test_excel_export(shop, tmp_path):
    s, admin = shop["s"], shop["admin"]
    _day_of_trading(shop)
    r = s.reports.daily_summary(admin, date.today())
    path = save_daily_summary(r, tmp_path / "day", "Sample Corner Store", "₱")
    assert path.suffix == ".xlsx"
    ws = load_workbook(path).active
    values = {row[0]: row[1] for row in ws.iter_rows(values_only=True) if row and row[0]}
    assert ws["A1"].value == "Sample Corner Store"
    assert values["Net sales"] == 150 and values["Net profit"] == -250
    assert values["Total expenses"] == 340 and values["Total over / short"] == -10
    money_cell = next(row[1] for row in ws.iter_rows() if row[0].value == "Net profit")
    assert "#,##0.00" in money_cell.number_format and money_cell.font.bold

"""Shifts, cash drawer, blind close and expenses."""
from decimal import Decimal as D

import pytest

from database.connection import DatabaseError
from models.cart import Cart
from services.errors import PermissionDenied, ValidationError
from services.product_service import ProductInput
from services.purchasing_service import ReceiveLine
from services.sale_service import PaymentInput

pytestmark = pytest.mark.integration


@pytest.fixture()
def shop(fresh_services):
    s = fresh_services
    admin = s.auth.create_first_admin("owner", "Owner", "Owner-Pass-1")
    roles = {r.code: r.id for r in s.users.list_roles(admin)}
    for u, role in (("cash1", "cashier"), ("cash2", "cashier"), ("boss", "manager")):
        s.users.create_user(admin, username=u, full_name=u.title(), role_id=roles[role],
                            temporary_password="TempPass-1")
    unit = next(u.id for u in s.catalog.list_units(admin) if u.code == "pc")
    pid = s.products.create(admin, ProductInput(name="Soap", unit_id=unit, cost_price="20",
                                                selling_price="50", barcode="777"))
    s.purchasing.receive(admin, [ReceiveLine(pid, "100", unit_cost="20")])
    pm = {m.code: m.id for m in s.sales.payment_methods(admin)}
    login = lambda u: s.auth.login(u, "TempPass-1")  # noqa: E731
    return dict(s=s, admin=admin, pid=pid, pm=pm, cashier=login("cash1"), cashier2=login("cash2"),
                boss=login("boss"))


def sell(shop, who, qty, payments):
    s = shop["s"]
    cart = Cart()
    cart.add(s.products.get(who, shop["pid"]), qty)
    return s.sales.complete_sale(who, cart, payments)


def test_selling_needs_an_open_shift_and_links_it(shop):
    s, cashier = shop["s"], shop["cashier"]
    with pytest.raises(ValidationError, match="Open your shift first"):
        sell(shop, cashier, "1", [PaymentInput(shop["pm"]["CASH"], "50")])
    sid = s.shifts.open_shift(cashier, "500")
    with pytest.raises(ValidationError, match="already open"):
        s.shifts.open_shift(cashier, "100")
    r = sell(shop, cashier, "1", [PaymentInput(shop["pm"]["CASH"], "50")])
    assert s.db.fetch_one("SELECT shift_id FROM sales WHERE id = %s", (r.sale_id,))["shift_id"] == sid
    # one open shift per person is enforced by the database too
    with pytest.raises(DatabaseError):
        s.db.execute("INSERT INTO shifts (shift_no, user_id, open_user_id, opening_float) "
                     "VALUES ('X', %s, %s, 0)", (cashier.user_id, cashier.user_id))
    # the store can switch the rule off
    s.db.execute("UPDATE app_settings SET setting_value = '0' WHERE setting_key = 'require_shift'")
    r2 = sell(shop, shop["cashier2"], "1", [PaymentInput(shop["pm"]["CASH"], "50")])
    assert s.db.fetch_one("SELECT shift_id FROM sales WHERE id = %s", (r2.sale_id,))["shift_id"] is None


def test_expected_cash_blind_close_and_report(shop):
    s, cashier, boss, pm = shop["s"], shop["cashier"], shop["boss"], shop["pm"]
    sid = s.shifts.open_shift(cashier, "500")
    sell(shop, cashier, "2", [PaymentInput(pm["CASH"], "200")])                 # +100 cash (change 100)
    sell(shop, cashier, "1", [PaymentInput(pm["GCASH"], "50", "GC-1")])          # not cash
    sell(shop, cashier, "2", [PaymentInput(pm["GCASH"], "40", "GC-2"),
                              PaymentInput(pm["CASH"], "100")])                  # +60 cash
    s.shifts.cash_movement(cashier, "cash_in", "100", "coins for change", approved_by=boss.user_id)
    s.shifts.cash_movement(cashier, "cash_out", "50", "to the safe", approved_by=boss.user_id)
    e1 = s.expenses.add(cashier, category=1, amount="30", description="ice", approved_by=boss.user_id)
    s.expenses.add(cashier, category=2, amount="25", approved_by=boss.user_id)
    s.expenses.void(boss, e1, "typed twice")                                      # +30 back
    # 500 + 160 + 100 - 50 - 30 - 25 + 30 = 685
    own = s.shifts.summary(cashier, sid)
    assert own.expected_cash is None and own.sales_count == 3        # blind for the cashier
    mgr = s.shifts.summary(boss, sid)
    assert mgr.expected_cash == D("685.00") and mgr.cash_sales == D("160.00")
    assert {p["name"]: p["amount"] for p in mgr.payments} == {"Cash": D("160.00"), "GCash": D("90.00")}
    assert [r["expected_cash"] for r in s.shifts.list_shifts(cashier, mgr.shift["opened_at"].date(),
                                                             mgr.shift["opened_at"].date())] == [None]
    with pytest.raises(PermissionDenied):
        s.shifts.close_shift(shop["cashier2"], sid, "600")
    res = s.shifts.close_shift(cashier, sid, "680.00", "one 5 coin missing")
    assert res.expected_cash == D("685.00") and res.shift["difference"] == D("-5.00")
    assert res.shift["status"] == "closed" and res.shift["closed_by"] == cashier.user_id
    assert s.shifts.summary(cashier, sid).expected_cash == D("685.00")   # visible after closing
    with pytest.raises(ValidationError, match="already closed"):
        s.shifts.close_shift(cashier, sid, "1")
    with pytest.raises(ValidationError, match="Open your shift"):
        sell(shop, cashier, "1", [PaymentInput(pm["CASH"], "50")])
    from services.receipt_service import build_shift_report
    report = build_shift_report(res, s.shifts.movements(cashier, sid), s.settings.get()).plain_text()
    assert "SHORT" in report and "685.00" in report and "Expense voided" in report
    assert len(s.audit.search(shop["admin"], text="shift.closed")) == 1
    # a new shift starts fresh
    sid2 = s.shifts.open_shift(cashier, "300")
    assert s.shifts.summary(boss, sid2).expected_cash == D("300.00")


def test_cash_movement_rules(shop):
    s, cashier, boss = shop["s"], shop["cashier"], shop["boss"]
    with pytest.raises(ValidationError, match="Open your shift"):
        s.shifts.cash_movement(boss, "cash_in", "10", "x")
    sid = s.shifts.open_shift(cashier, "100")
    with pytest.raises(PermissionDenied, match="manager must approve"):
        s.shifts.cash_movement(cashier, "cash_out", "10", "safe")
    with pytest.raises(PermissionDenied, match="not valid"):
        s.shifts.cash_movement(cashier, "cash_out", "10", "safe",
                               approved_by=shop["cashier2"].user_id)
    with pytest.raises(ValidationError, match="reason"):
        s.shifts.cash_movement(cashier, "cash_out", "10", "  ", approved_by=boss.user_id)
    with pytest.raises(ValidationError, match="not that much cash"):
        s.shifts.cash_movement(cashier, "cash_out", "100.01", "safe", approved_by=boss.user_id)
    a = s.shifts.cash_movement(cashier, "cash_out", "40", "safe", approved_by=boss.user_id, token="t1")
    b = s.shifts.cash_movement(cashier, "cash_out", "40", "safe", approved_by=boss.user_id, token="t1")
    assert a == b and s.shifts.summary(boss, sid).expected_cash == D("60.00")
    moves = s.shifts.movements(cashier, sid)
    assert moves[0]["approved_by_name"] == "Boss" and moves[0]["label"] == "Cash out"
    for sql in ("UPDATE cash_movements SET amount = 1", "DELETE FROM cash_movements"):
        with pytest.raises(DatabaseError):
            s.db.execute(sql)


def test_expenses_rules(shop):
    s, cashier, boss, admin = shop["s"], shop["cashier"], shop["boss"], shop["admin"]
    with pytest.raises(ValidationError, match="Open your shift"):
        s.expenses.add(boss, category=1, amount="10")
    with pytest.raises(PermissionDenied):
        s.expenses.add(cashier, category=1, amount="10", paid_from="other")
    with pytest.raises(PermissionDenied):
        s.expenses.add(cashier, category="Brand new kind", amount="10", paid_from="drawer")
    other = s.expenses.add(boss, category="Internet", amount="1299", paid_from="other",
                           description="monthly", token="e-1")
    assert s.expenses.add(boss, category="Internet", amount="1299", paid_from="other",
                          token="e-1") == other                                  # saved once
    sid = s.shifts.open_shift(cashier, "50")
    with pytest.raises(ValidationError, match="not that much cash"):
        s.expenses.add(cashier, category=1, amount="60", approved_by=boss.user_id)
    drawer = s.expenses.add(cashier, category=1, amount="20", approved_by=boss.user_id)
    s.shifts.close_shift(cashier, sid, "30")
    s.expenses.void(boss, drawer, "wrong")
    assert s.shifts.summary(boss, sid).shift["difference"] == D("0.00")   # closed shift unchanged
    with pytest.raises(ValidationError, match="already voided"):
        s.expenses.void(boss, drawer, "again")
    with pytest.raises(ValidationError, match="why"):
        s.expenses.void(boss, other, "")
    with pytest.raises(PermissionDenied):
        s.expenses.list(cashier, shop["s"].shifts.repo.get_shift(sid)["opened_at"].date(),
                        shop["s"].shifts.repo.get_shift(sid)["opened_at"].date())
    from datetime import date, timedelta
    rows = s.expenses.list(admin, date.today() - timedelta(days=1), date.today())
    assert {(r["category"], r["status"]) for r in rows} == {("Internet", "active"), ("Ice", "void")}
    with pytest.raises(ValidationError, match="future"):
        s.expenses.add(boss, category=1, amount="1", paid_from="other",
                       expense_date=date.today() + timedelta(days=1))
    with pytest.raises(DatabaseError):
        s.db.execute("DELETE FROM expenses")


def test_delivery_paid_from_drawer(shop):
    s, boss, pid = shop["s"], shop["boss"], shop["pid"]
    with pytest.raises(ValidationError, match="Open your shift"):
        s.purchasing.receive(boss, [ReceiveLine(pid, "1", unit_cost="20")], paid_from_drawer=True)
    sid = s.shifts.open_shift(boss, "1000")
    s.purchasing.receive(boss, [ReceiveLine(pid, "10", line_total="210")], paid_from_drawer=True)
    with pytest.raises(ValidationError, match="not that much cash"):
        s.purchasing.receive(boss, [ReceiveLine(pid, "100", unit_cost="20")], paid_from_drawer=True)
    summ = s.shifts.summary(boss, sid)
    assert summ.movements == {"purchase": D("210.00")} and summ.expected_cash == D("790.00")


def test_manager_closes_forgotten_shift(shop):
    s, cashier, boss = shop["s"], shop["cashier"], shop["boss"]
    sid = s.shifts.open_shift(cashier, "200")
    assert [r["id"] for r in s.shifts.open_shifts(boss)] == [sid]
    with pytest.raises(PermissionDenied):
        s.shifts.open_shifts(cashier)
    res = s.shifts.close_shift(boss, sid, "200")
    assert res.shift["closed_by"] == boss.user_id and res.shift["difference"] == D("0.00")
    assert s.shifts.current(cashier) is None

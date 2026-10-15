"""Cashier shifts and the cash drawer.

A cashier opens a shift with the starting cash (change fund) before selling.
Sales are linked to the open shift automatically (SaleService.complete_sale).
Cash put in or taken out of the drawer is recorded as cash_movements.

Closing is a BLIND count: the cashier types the cash counted; only then the
expected amount and the difference (over / short) are shown.

    expected = opening cash + cash sales + cash in - cash out - expenses
               - deliveries paid from the drawer + voided expenses put back
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from database.connection import Database
from models.user import Session
from repositories.cash_repository import CashRepository
from repositories.sale_repository import SaleRepository
from repositories.settings_repository import SettingsRepository
from repositories.user_repository import UserRepository
from services.audit_service import AuditService
from services.errors import NotFound, PermissionDenied, ValidationError
from services.product_service import parse_money_field
from utils.money import ZERO, to_money

log = logging.getLogger(__name__)

MOVEMENT_LABELS = {"cash_in": "Cash in", "cash_out": "Cash out", "expense": "Expense",
                   "purchase": "Delivery paid", "expense_void": "Expense voided (put back)"}
_SIGN = {"cash_in": 1, "expense_void": 1, "cash_out": -1, "expense": -1, "purchase": -1}


def verify_approver(users: UserRepository, cur, session: Session, approved_by: int | None,
                    permission: str, action: str) -> int | None:
    """None when the user may do it alone; the approver's id when a manager approved.
    The approver is re-checked in the database (active, has the permission)."""
    if session.can(permission):
        return None
    if not approved_by or approved_by == session.user_id:
        raise PermissionDenied(f"A manager must approve this: {action}.")
    row = users.get_by_id(approved_by, cur)
    if row is None or not row["is_active"] or permission not in users.permissions_for_role(row["role_id"], cur):
        raise PermissionDenied("The approval is not valid. Ask a manager again.")
    return approved_by


def drawer_cash(repo: CashRepository, shift: dict, cur=None) -> Decimal:
    """Cash that should be in the drawer of this shift right now."""
    sid = int(shift["id"])
    cash_sales = sum((Decimal(p["amount"]) for p in repo.shift_payments(sid, cur) if p["is_cash"]), ZERO)
    moves = repo.movement_totals(sid, cur)
    return to_money(Decimal(shift["opening_float"]) + cash_sales
                    + sum((_SIGN[k] * Decimal(v) for k, v in moves.items()), ZERO))


@dataclass(frozen=True)
class ShiftSummary:
    shift: dict
    sales_count: int
    sales_total: Decimal
    payments: list[dict]            # per method: name, is_cash, amount, n
    cash_sales: Decimal
    movements: dict[str, Decimal]   # kind -> total
    expected_cash: Decimal | None   # None = hidden (blind count)


class ShiftService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.repo = CashRepository(db)
        self.numbers = SaleRepository(db)
        self.users = UserRepository(db)
        self.settings = SettingsRepository(db)
        self.audit = audit or AuditService(db)

    def required(self) -> bool:
        return self.settings.get_all().get("require_shift", "1") == "1"

    # ------------------------------------------------------------------ reads
    def current(self, session: Session) -> dict | None:
        """The logged-in user's open shift (or None)."""
        return self.repo.open_shift_for(session.user_id)

    def summary(self, session: Session, shift_id: int) -> ShiftSummary:
        shift = self.repo.get_shift(shift_id)
        if shift is None:
            raise NotFound("This shift was not found.")
        own = shift["user_id"] == session.user_id
        if not (session.can("shifts.manage") or (own and session.can("shifts.own"))):
            raise PermissionDenied("You can only see your own shifts.")
        return self._summary(shift, blind=(shift["status"] == "open" and not session.can("shifts.manage")))

    def _summary(self, shift: dict, blind: bool, cur=None) -> ShiftSummary:
        sid = int(shift["id"])
        sales = self.repo.shift_sales(sid, cur)
        payments = self.repo.shift_payments(sid, cur)
        cash_sales = sum((Decimal(p["amount"]) for p in payments if p["is_cash"]), ZERO)
        moves = {k: to_money(v) for k, v in self.repo.movement_totals(sid, cur).items()}
        expected = drawer_cash(self.repo, shift, cur)
        return ShiftSummary(shift, int(sales["n"]), to_money(sales["total"]), payments, cash_sales,
                            moves, None if blind else expected)

    def list_shifts(self, session: Session, date_from: date, date_to: date) -> list[dict]:
        if session.can("shifts.manage"):
            return self.repo.list_shifts(date_from, date_to)
        session.require("shifts.own", "view shifts")
        rows = self.repo.list_shifts(date_from, date_to, session.user_id)
        for r in rows:          # blind: no expected amount while the shift is open
            if r["status"] == "open":
                r["expected_cash"] = None
        return rows

    def open_shifts(self, session: Session) -> list[dict]:
        session.require("shifts.manage", "view all shifts")
        return self.repo.open_shifts()

    def movements(self, session: Session, shift_id: int) -> list[dict]:
        self.summary(session, shift_id)          # permission check
        rows = self.repo.movements(shift_id)
        for r in rows:
            r["label"] = MOVEMENT_LABELS.get(r["kind"], r["kind"])
        return rows

    # ----------------------------------------------------------------- writes
    def open_shift(self, session: Session, opening_float: str | Decimal) -> int:
        session.require("shifts.own", "open a shift")
        amount = parse_money_field(str(opening_float), "Starting cash", allow_zero=True)
        with self.db.transaction() as cur:
            if self.repo.open_shift_for(session.user_id, cur, lock=True):
                raise ValidationError("Your shift is already open.")
            now = self.numbers.db_now(cur)
            n = self.numbers.next_number(cur, "shift", now["period"])
            shift_no = f"SH{now['period']}-{n:02d}"
            shift_id = self.repo.insert_shift(cur, shift_no, session.user_id, amount)
            self.audit.record(cur, "shift.opened", session=session, entity_type="shift",
                              entity_id=shift_no, details={"starting_cash": amount})
        log.info("Shift %s opened by %s", shift_no, session.username)
        return shift_id

    def cash_movement(self, session: Session, kind: str, amount: str | Decimal, reason: str,
                      approved_by: int | None = None, token: str | None = None) -> int:
        """Cash in (more change) or cash out (e.g. to the safe) during your own shift."""
        session.require("shifts.own", "use the cash drawer")
        if kind not in ("cash_in", "cash_out"):
            raise ValidationError("Choose cash in or cash out.")
        value = parse_money_field(str(amount), "Amount", allow_zero=False)
        reason = " ".join((reason or "").split())[:200]
        if not reason:
            raise ValidationError("Write the reason (e.g. 'more coins for change', 'to the safe').")
        token = token or str(uuid.uuid4())
        with self.db.transaction() as cur:
            done = self.repo.find_movement(token, cur)
            if done:
                return int(done["id"])
            shift = self.repo.open_shift_for(session.user_id, cur, lock=True)
            if shift is None:
                raise ValidationError("Open your shift first.")
            approver = verify_approver(self.users, cur, session, approved_by, "cash.movements",
                                       MOVEMENT_LABELS[kind].lower())
            if kind == "cash_out":
                if value > drawer_cash(self.repo, shift, cur):
                    raise ValidationError("There is not that much cash in the drawer.")
            mid = self.repo.insert_movement(cur, token=token, shift_id=int(shift["id"]), kind=kind,
                                            amount=value, reason=reason, user_id=session.user_id,
                                            approved_by=approver)
            self.audit.record(cur, f"cash.{kind}", session=session, entity_type="shift",
                              entity_id=shift["shift_no"],
                              details={"amount": value, "reason": reason, "approved_by": approver})
        return mid

    def close_shift(self, session: Session, shift_id: int, counted: str | Decimal,
                    note: str = "") -> ShiftSummary:
        """Blind close: returns the summary with expected, counted and difference."""
        counted_amt = parse_money_field(str(counted), "Cash counted", allow_zero=True)
        note = " ".join((note or "").split())[:200] or None
        with self.db.transaction() as cur:
            shift = self.repo.get_shift(shift_id, cur, lock=True)
            if shift is None:
                raise NotFound("This shift was not found.")
            if shift["status"] != "open":
                raise ValidationError("This shift is already closed.")
            if shift["user_id"] == session.user_id:
                session.require("shifts.own", "close a shift")
            else:
                session.require("shifts.manage", "close another person's shift")
            s = self._summary(shift, blind=False, cur=cur)
            diff = counted_amt - s.expected_cash
            self.repo.close_shift(cur, shift_id, closed_by=session.user_id, expected=s.expected_cash,
                                  counted=counted_amt, difference=diff, note=note)
            self.audit.record(cur, "shift.closed", session=session, entity_type="shift",
                              entity_id=shift["shift_no"],
                              details={"expected": s.expected_cash, "counted": counted_amt,
                                       "difference": diff, "sales": s.sales_count, "note": note})
            closed = self.repo.get_shift(shift_id, cur)
        log.info("Shift %s closed: expected %s counted %s", shift["shift_no"], s.expected_cash, counted_amt)
        return ShiftSummary(closed, s.sales_count, s.sales_total, s.payments, s.cash_sales,
                            s.movements, s.expected_cash)

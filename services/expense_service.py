"""Expenses: paid from the cash drawer (during a shift) or from other money.

A drawer expense also writes a cash movement in the same transaction, so the
shift's expected cash goes down. Expenses are never deleted; a manager can void
one with a reason (if its shift is still open, the cash is counted back in).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from database.connection import Database
from models.user import Session
from repositories.cash_repository import CashRepository
from repositories.user_repository import UserRepository
from services.audit_service import AuditService
from services.errors import NotFound, PermissionDenied, ValidationError
from services.product_service import parse_money_field
from services.shift_service import drawer_cash, verify_approver


class ExpenseService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.repo = CashRepository(db)
        self.users = UserRepository(db)
        self.audit = audit or AuditService(db)

    @staticmethod
    def _may_record(session: Session) -> bool:
        return session.can("expenses.manage") or session.can("shifts.own")

    def categories(self, session: Session) -> list[dict]:
        if not self._may_record(session):
            raise PermissionDenied("Your account is not allowed to record expenses.")
        return self.repo.categories()

    def add(self, session: Session, *, category: int | str, amount: str | Decimal, description: str = "",
            paid_from: str = "drawer", expense_date: date | None = None,
            approved_by: int | None = None, token: str | None = None) -> int:
        """category: an id, or a new category name (managers)."""
        if not self._may_record(session):
            raise PermissionDenied("Your account is not allowed to record expenses.")
        if paid_from not in ("drawer", "other"):
            raise ValidationError("Choose where the money came from.")
        if paid_from == "other":
            session.require("expenses.manage", "record expenses paid from other money")
        value = parse_money_field(str(amount), "Amount", allow_zero=False)
        description = " ".join((description or "").split())[:200] or None
        token = token or str(uuid.uuid4())
        with self.db.transaction() as cur:
            done = self.repo.find_expense(token, cur)
            if done:
                return int(done["id"])
            cat_id, cat_name = self._category(cur, session, category)
            approver = None
            shift = None
            if paid_from == "drawer":
                shift = self.repo.open_shift_for(session.user_id, cur, lock=True)
                if shift is None:
                    raise ValidationError("Open your shift first - drawer expenses belong to a shift.")
                approver = verify_approver(self.users, cur, session, approved_by, "cash.movements",
                                           "pay an expense from the drawer")
                if value > drawer_cash(self.repo, shift, cur):
                    raise ValidationError("There is not that much cash in the drawer.")
            when = expense_date or date.today()
            if when > date.today():
                raise ValidationError("The expense date cannot be in the future.")
            exp_id = self.repo.insert_expense(
                cur, token=token, category_id=cat_id, description=description, amount=value,
                paid_from=paid_from, shift_id=int(shift["id"]) if shift else None, expense_date=when,
                user_id=session.user_id, approved_by=approver)
            if shift:
                self.repo.insert_movement(cur, token=str(uuid.uuid4()), shift_id=int(shift["id"]),
                                          kind="expense", amount=value,
                                          reason=f"{cat_name}" + (f": {description}" if description else ""),
                                          user_id=session.user_id, approved_by=approver,
                                          reference_type="expense", reference_id=exp_id)
            self.audit.record(cur, "expense.added", session=session, entity_type="expense",
                              entity_id=exp_id,
                              details={"category": cat_name, "amount": value, "paid_from": paid_from,
                                       "description": description, "approved_by": approver})
        return exp_id

    def _category(self, cur, session: Session, category: int | str) -> tuple[int, str]:
        if isinstance(category, int):
            row = self.repo.get_category(category, cur)
            if row is None or not row["is_active"]:
                raise ValidationError("Choose the kind of expense.")
            return int(row["id"]), row["name"]
        name = " ".join(str(category or "").split())[:60]
        if not name:
            raise ValidationError("Choose the kind of expense.")
        row = self.repo.category_by_name(name, cur)
        if row:
            return int(row["id"]), row["name"]
        session.require("expenses.manage", "add a new kind of expense")
        cid = self.repo.insert_category(cur, name)
        self.audit.record(cur, "expense_category.created", session=session,
                          entity_type="expense_category", entity_id=cid, details={"name": name})
        return cid, name

    def void(self, session: Session, expense_id: int, reason: str) -> None:
        session.require("expenses.manage", "void expenses")
        reason = " ".join((reason or "").split())[:200]
        if not reason:
            raise ValidationError("Write why this expense is being voided.")
        with self.db.transaction() as cur:
            exp = self.repo.get_expense(expense_id, cur, lock=True)
            if exp is None:
                raise NotFound("This expense was not found.")
            if exp["status"] == "void":
                raise ValidationError("This expense was already voided.")
            self.repo.void_expense(cur, expense_id, reason, session.user_id)
            put_back = False
            if exp["paid_from"] == "drawer":
                shift = self.repo.get_shift(int(exp["shift_id"]), cur, lock=True)
                if shift and shift["status"] == "open":
                    self.repo.insert_movement(cur, token=str(uuid.uuid4()), shift_id=int(shift["id"]),
                                              kind="expense_void", amount=exp["amount"],
                                              reason=f"Voided: {reason}", user_id=session.user_id,
                                              reference_type="expense", reference_id=expense_id)
                    put_back = True
            self.audit.record(cur, "expense.voided", session=session, entity_type="expense",
                              entity_id=expense_id,
                              details={"amount": exp["amount"], "category": exp["category"],
                                       "reason": reason, "cash_put_back_in_open_shift": put_back})

    def list(self, session: Session, date_from: date, date_to: date, include_void: bool = True) -> list[dict]:
        session.require("expenses.manage", "view expenses")
        return self.repo.list_expenses(date_from, date_to, include_void)

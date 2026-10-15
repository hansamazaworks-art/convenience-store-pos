"""User account management (administrators only)."""
from __future__ import annotations

import re

from database.connection import Database
from models.user import Role, Session, UserRecord
from repositories.user_repository import UserRepository
from services.audit_service import AuditService
from services.errors import NotFound, ValidationError
from utils.security import hash_password

_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,50}$")


def clean_username(username: str) -> str:
    u = (username or "").strip()
    if not _USERNAME_RE.match(u):
        raise ValidationError(
            "Username must be 3 to 50 characters: letters, numbers, dot, dash or underscore "
            "(no spaces)."
        )
    return u


def clean_full_name(full_name: str) -> str:
    n = " ".join((full_name or "").split())
    if not n:
        raise ValidationError("Enter the person's full name.")
    if len(n) > 100:
        raise ValidationError("The name is too long (maximum 100 characters).")
    return n


class UserService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.repo = UserRepository(db)
        self.audit = audit or AuditService(db)

    def list_users(self, session: Session) -> list[UserRecord]:
        session.require("users.manage", "manage user accounts")
        return [UserRecord.from_row(r) for r in self.repo.list_users()]

    def list_roles(self, session: Session) -> list[Role]:
        session.require("users.manage", "manage user accounts")
        return [Role(int(r["id"]), r["code"], r["name"], r["description"])
                for r in self.repo.list_roles()]

    def create_user(self, session: Session, *, username: str, full_name: str, role_id: int,
                    temporary_password: str) -> int:
        session.require("users.manage", "create user accounts")
        username, full_name = clean_username(username), clean_full_name(full_name)
        pw_hash = hash_password(temporary_password)
        with self.db.transaction() as cur:
            if self.repo.get_by_username(username, cur):
                raise ValidationError(f"The username '{username}' is already taken.")
            role = self.repo.get_role(role_id, cur)
            if role is None:
                raise ValidationError("Choose a role.")
            user_id = self.repo.insert(cur, username=username, full_name=full_name,
                                       password_hash=pw_hash, role_id=role_id,
                                       must_change_password=True, created_by=session.user_id)
            self.audit.record(cur, "user.created", session=session, entity_type="user",
                              entity_id=user_id,
                              details={"username": username, "full_name": full_name,
                                       "role": role["code"]})
        return user_id

    def update_user(self, session: Session, user_id: int, *, full_name: str, role_id: int) -> None:
        session.require("users.manage", "edit user accounts")
        full_name = clean_full_name(full_name)
        with self.db.transaction() as cur:
            user = self._get(cur, user_id)
            role = self.repo.get_role(role_id, cur)
            if role is None:
                raise ValidationError("Choose a role.")
            if user["role_code"] == "admin" and role["code"] != "admin":
                if user_id == session.user_id:
                    raise ValidationError("You cannot remove your own administrator role.")
                self._ensure_another_admin(cur, user_id)
            self.repo.update_profile(cur, user_id, full_name, role_id)
            self.audit.record(cur, "user.updated", session=session, entity_type="user",
                              entity_id=user_id,
                              details={"username": user["username"],
                                       "full_name": [user["full_name"], full_name],
                                       "role": [user["role_code"], role["code"]]})

    def set_active(self, session: Session, user_id: int, active: bool) -> None:
        session.require("users.manage", "enable or disable user accounts")
        if user_id == session.user_id and not active:
            raise ValidationError("You cannot disable your own account.")
        with self.db.transaction() as cur:
            user = self._get(cur, user_id)
            if not active and user["role_code"] == "admin" and user["is_active"]:
                self._ensure_another_admin(cur, user_id)
            self.repo.set_active(cur, user_id, active)
            self.audit.record(cur, "user.enabled" if active else "user.disabled",
                              session=session, entity_type="user", entity_id=user_id,
                              details={"username": user["username"]})

    def reset_password(self, session: Session, user_id: int, temporary_password: str) -> None:
        """Give the user a temporary password; they must change it at next login.
        Also unlocks the account."""
        session.require("users.manage", "reset passwords")
        pw_hash = hash_password(temporary_password)
        with self.db.transaction() as cur:
            user = self._get(cur, user_id)
            self.repo.set_password(cur, user_id, pw_hash, must_change=True)
            self.audit.record(cur, "user.password_reset", session=session, entity_type="user",
                              entity_id=user_id, details={"username": user["username"]})

    # ---------------------------------------------------------------- helpers
    def _get(self, cur, user_id: int) -> dict:
        user = self.repo.get_by_id(user_id, cur, for_update=True)
        if user is None:
            raise NotFound("This user no longer exists. Refresh the list.")
        return user

    def _ensure_another_admin(self, cur, user_id: int) -> None:
        if self.repo.count_active_admins(cur, exclude_user_id=user_id) == 0:
            raise ValidationError(
                "This is the only active administrator. Create or enable another "
                "administrator first, so the store is never locked out."
            )

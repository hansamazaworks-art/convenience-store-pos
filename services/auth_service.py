"""Login, logout, passwords, first-time admin setup and manager approval."""
from __future__ import annotations

import logging

from database.connection import Database
from models.user import Session
from repositories.user_repository import UserRepository
from services.audit_service import AuditService
from services.errors import AuthError, ValidationError
from services.user_service import clean_full_name, clean_username
from utils.security import burn_time, hash_password, validate_new_password, verify_password

log = logging.getLogger(__name__)

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 5
_WRONG = "Wrong username or password."


class AuthService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.audit = audit or AuditService(db)

    # ------------------------------------------------------- first-time setup
    def needs_first_admin(self) -> bool:
        return self.users.count_users() == 0

    def create_first_admin(self, username: str, full_name: str, password: str) -> Session:
        username, full_name = clean_username(username), clean_full_name(full_name)
        pw_hash = hash_password(password)
        with self.db.transaction() as cur:
            # Lock a fixed settings row so two setup windows cannot both succeed.
            cur.execute("SELECT setting_key FROM app_settings WHERE setting_key = 'store_name' "
                        "FOR UPDATE")
            cur.fetchall()
            if self.users.count_users(cur) > 0:
                raise ValidationError("An administrator account already exists. Please log in.")
            role = self.users.get_role_by_code("admin", cur)
            user_id = self.users.insert(cur, username=username, full_name=full_name,
                                        password_hash=pw_hash, role_id=role["id"],
                                        must_change_password=False, created_by=None)
            self.audit.record(cur, "user.first_admin_created", user_id=user_id,
                              username=username, entity_type="user", entity_id=user_id)
            self.users.record_successful_login(cur, user_id)
            self.audit.record(cur, "auth.login", user_id=user_id, username=username)
            row = self.users.get_by_id(user_id, cur)
            return self._session(row, cur)

    # ------------------------------------------------------------------ login
    def login(self, username: str, password: str) -> Session:
        username = (username or "").strip()
        if not username or not password:
            raise AuthError("Enter your username and password.")

        failure: str | None = None
        session: Session | None = None
        with self.db.transaction() as cur:
            row = self.users.get_by_username(username, cur, for_update=True)
            if row is None:
                burn_time()
                self.audit.record(cur, "auth.login_failed", username=username,
                                  details={"reason": "unknown user"})
                failure = _WRONG
            elif row["is_locked"]:
                self.audit.record(cur, "auth.login_blocked_locked", user_id=row["id"],
                                  username=row["username"])
                failure = (f"This account is locked for {LOCK_MINUTES} minutes because of "
                           "too many wrong passwords.\nTry again later, or ask an administrator "
                           "to reset the password.")
            elif not verify_password(password, row["password_hash"]):
                locked = self.users.record_failed_login(cur, row["id"], MAX_FAILED_ATTEMPTS,
                                                        LOCK_MINUTES)
                self.audit.record(cur, "auth.login_failed", user_id=row["id"],
                                  username=row["username"],
                                  details={"reason": "wrong password", "locked": locked})
                failure = _WRONG
                if locked:
                    failure += (f"\n\nThe account is now locked for {LOCK_MINUTES} minutes.")
            elif not row["is_active"]:
                self.audit.record(cur, "auth.login_blocked_inactive", user_id=row["id"],
                                  username=row["username"])
                failure = "This account has been disabled. Ask an administrator."
            else:
                self.users.record_successful_login(cur, row["id"])
                self.audit.record(cur, "auth.login", user_id=row["id"], username=row["username"])
                session = self._session(row, cur)
        # The transaction is committed first, so failed attempts are counted.
        if failure:
            raise AuthError(failure)
        log.info("User %s logged in", session.username)
        return session

    def logout(self, session: Session) -> None:
        try:
            self.audit.record_now("auth.logout", session=session)
        except Exception:  # logging out must never be blocked
            log.exception("Could not record logout")

    # -------------------------------------------------------------- passwords
    def change_own_password(self, session: Session, current: str, new: str) -> Session:
        validate_new_password(new)
        if current == new:
            raise ValidationError("The new password must be different from the current one.")
        with self.db.transaction() as cur:
            row = self.users.get_by_id(session.user_id, cur, for_update=True)
            if row is None or not verify_password(current, row["password_hash"]):
                raise AuthError("The current password is wrong.")
            self.users.set_password(cur, session.user_id, hash_password(new), must_change=False)
            self.audit.record(cur, "auth.password_changed", session=session,
                              entity_type="user", entity_id=session.user_id)
            row = self.users.get_by_id(session.user_id, cur)
            return self._session(row, cur)

    # --------------------------------------------------------- manager approval
    def approve(self, username: str, password: str, permission: str, action: str,
                requested_by: Session | None = None) -> Session:
        """A second person (e.g. a manager) types their own login to approve an
        action the current user may not do alone. Returns the approver.
        Used later for discounts, voids and refunds."""
        username = (username or "").strip()
        row = self.users.get_by_username(username) if username else None
        if row is None:
            burn_time()
            raise AuthError(_WRONG)
        if row["is_locked"] or not row["is_active"] or not verify_password(password, row["password_hash"]):
            self.audit.record_now("auth.approval_failed", user_id=row["id"], username=row["username"],
                                  details={"for": action, "requested_by":
                                           requested_by.username if requested_by else None})
            raise AuthError(_WRONG)
        approver = self._session(row)
        approver.require(permission, f"approve: {action}")
        return approver

    # ---------------------------------------------------------------- helpers
    def _session(self, row: dict, cur=None) -> Session:
        return Session(
            user_id=int(row["id"]), username=row["username"], full_name=row["full_name"],
            role_code=row["role_code"], role_name=row["role_name"],
            permissions=frozenset(self.users.permissions_for_role(row["role_id"], cur)),
            must_change_password=bool(row["must_change_password"]),
        )

"""All SQL for users, roles and permissions."""
from __future__ import annotations

from repositories.base import Repository

_USER_SELECT = """
SELECT u.id, u.username, u.full_name, u.password_hash, u.role_id,
       r.code AS role_code, r.name AS role_name,
       u.is_active, u.must_change_password, u.failed_attempts,
       u.locked_until, u.last_login_at, u.created_at,
       (u.locked_until IS NOT NULL AND u.locked_until > NOW()) AS is_locked
FROM users u
JOIN roles r ON r.id = u.role_id
"""


class UserRepository(Repository):
    # ---------------------------------------------------------------- reads
    def count_users(self, cur=None) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM users", (), cur)
        return int(row["n"])

    def get_by_username(self, username: str, cur=None, for_update: bool = False) -> dict | None:
        sql = _USER_SELECT + " WHERE u.username = %s" + (" FOR UPDATE" if for_update else "")
        return self._one(sql, (username,), cur)

    def get_by_id(self, user_id: int, cur=None, for_update: bool = False) -> dict | None:
        sql = _USER_SELECT + " WHERE u.id = %s" + (" FOR UPDATE" if for_update else "")
        return self._one(sql, (user_id,), cur)

    def list_users(self, cur=None) -> list[dict]:
        return self._all(_USER_SELECT + " ORDER BY u.is_active DESC, u.full_name", (), cur)

    def count_active_admins(self, cur, exclude_user_id: int | None = None) -> int:
        row = self._one(
            "SELECT COUNT(*) AS n FROM users u JOIN roles r ON r.id = u.role_id "
            "WHERE r.code = 'admin' AND u.is_active = 1 AND u.id <> %s FOR UPDATE",
            (exclude_user_id or 0,), cur,
        )
        return int(row["n"])

    def list_roles(self, cur=None) -> list[dict]:
        return self._all("SELECT id, code, name, description FROM roles ORDER BY sort_order", (), cur)

    def get_role(self, role_id: int, cur=None) -> dict | None:
        return self._one("SELECT id, code, name, description FROM roles WHERE id = %s", (role_id,), cur)

    def get_role_by_code(self, code: str, cur=None) -> dict | None:
        return self._one("SELECT id, code, name, description FROM roles WHERE code = %s", (code,), cur)

    def permissions_for_role(self, role_id: int, cur=None) -> set[str]:
        rows = self._all(
            "SELECT permission_code FROM role_permissions WHERE role_id = %s", (role_id,), cur
        )
        return {r["permission_code"] for r in rows}

    # --------------------------------------------------------------- writes
    def insert(self, cur, *, username: str, full_name: str, password_hash: str,
               role_id: int, must_change_password: bool, created_by: int | None) -> int:
        return self._exec(
            cur,
            "INSERT INTO users (username, full_name, password_hash, role_id, "
            "must_change_password, password_changed_at, created_by) "
            "VALUES (%s, %s, %s, %s, %s, NOW(), %s)",
            (username, full_name, password_hash, role_id, int(must_change_password), created_by),
        )

    def update_profile(self, cur, user_id: int, full_name: str, role_id: int) -> None:
        self._exec(cur, "UPDATE users SET full_name = %s, role_id = %s WHERE id = %s",
                   (full_name, role_id, user_id))

    def set_active(self, cur, user_id: int, active: bool) -> None:
        self._exec(cur, "UPDATE users SET is_active = %s WHERE id = %s", (int(active), user_id))

    def set_password(self, cur, user_id: int, password_hash: str, must_change: bool) -> None:
        self._exec(
            cur,
            "UPDATE users SET password_hash = %s, must_change_password = %s, "
            "password_changed_at = NOW(), failed_attempts = 0, locked_until = NULL WHERE id = %s",
            (password_hash, int(must_change), user_id),
        )

    def record_failed_login(self, cur, user_id: int, max_attempts: int, lock_minutes: int) -> bool:
        """Count a wrong password. Returns True if the account is now locked."""
        # locked_until is assigned first: MySQL applies SET items left to right.
        self._exec(
            cur,
            "UPDATE users SET "
            " locked_until = CASE WHEN failed_attempts + 1 >= %s "
            "                     THEN NOW() + INTERVAL %s MINUTE ELSE locked_until END, "
            " failed_attempts = CASE WHEN failed_attempts + 1 >= %s THEN 0 "
            "                        ELSE failed_attempts + 1 END "
            "WHERE id = %s",
            (max_attempts, lock_minutes, max_attempts, user_id),
        )
        row = self._one("SELECT (locked_until IS NOT NULL AND locked_until > NOW()) AS l "
                        "FROM users WHERE id = %s", (user_id,), cur)
        return bool(row and row["l"])

    def record_successful_login(self, cur, user_id: int) -> None:
        self._exec(cur, "UPDATE users SET failed_attempts = 0, locked_until = NULL, "
                        "last_login_at = NOW() WHERE id = %s", (user_id,))

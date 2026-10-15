"""SQL for the append-only audit log."""
from __future__ import annotations

from datetime import date, timedelta

from repositories.base import Repository


class AuditRepository(Repository):
    def insert(self, cur, *, user_id, username, action, entity_type, entity_id,
               details, workstation) -> int:
        return self._exec(
            cur,
            "INSERT INTO audit_log (user_id, username, action, entity_type, entity_id, "
            "details, workstation) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, username, action, entity_type, entity_id, details, workstation),
        )

    def search(self, *, text: str = "", date_from: date | None = None,
               date_to: date | None = None, limit: int = 500, cur=None) -> list[dict]:
        where, params = [], []
        if date_from:
            where.append("created_at >= %s")
            params.append(date_from)
        if date_to:
            where.append("created_at < %s")
            params.append(date_to + timedelta(days=1))
        if text:
            safe = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{safe}%"
            where.append("(action LIKE %s OR username LIKE %s OR entity_type LIKE %s "
                         "OR entity_id LIKE %s OR details LIKE %s)")
            params += [like] * 5
        sql = ("SELECT id, created_at, username, action, entity_type, entity_id, details, "
               "workstation FROM audit_log")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(int(limit))
        return self._all(sql, params, cur)

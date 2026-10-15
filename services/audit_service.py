"""Writes and reads the audit log ("who did what, when")."""
from __future__ import annotations

import json
import logging
import socket
from datetime import date

from database.connection import Database
from models.user import Session
from repositories.audit_repository import AuditRepository

log = logging.getLogger(__name__)
_WORKSTATION = (socket.gethostname() or "unknown")[:100]


class AuditService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.repo = AuditRepository(db)

    def record(self, cur, action: str, *, session: Session | None = None,
               user_id: int | None = None, username: str | None = None,
               entity_type: str | None = None, entity_id: object = None,
               details: dict | None = None) -> None:
        """Add an entry inside the caller's transaction (so it is saved
        together with the change it describes, or not at all)."""
        if session is not None:
            user_id, username = session.user_id, session.username
        self.repo.insert(
            cur,
            user_id=user_id,
            username=(username or None) and username[:50],
            action=action[:60],
            entity_type=entity_type,
            entity_id=None if entity_id is None else str(entity_id)[:40],
            details=json.dumps(details, default=str, ensure_ascii=False) if details else None,
            workstation=_WORKSTATION,
        )

    def record_now(self, action: str, **kwargs) -> None:
        """Add an entry in its own transaction."""
        with self.db.transaction() as cur:
            self.record(cur, action, **kwargs)

    def search(self, session: Session, *, text: str = "", date_from: date | None = None,
               date_to: date | None = None, limit: int = 500) -> list[dict]:
        session.require("audit.view", "view the audit log")
        return self.repo.search(text=text.strip(), date_from=date_from, date_to=date_to, limit=limit)

"""System health checks used by the start-up screen."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from database.connection import Database, DatabaseError
from database.migrator import Migrator

log = logging.getLogger(__name__)


@dataclass
class HealthResult:
    ok: bool
    summary: str


class SystemService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def check(self) -> HealthResult:
        try:
            info = self.db.server_info()
            applied, pending, warnings = Migrator(self.db).status()
        except DatabaseError as exc:
            log.warning("Health check failed: %s", exc.detail or exc.user_message)
            return HealthResult(False, exc.user_message)
        lines = [
            f"Database: {info.get('db')}",
            f"Server version: {info.get('version')}",
            f"Database updates applied: {len(applied)}",
        ]
        ok = True
        if pending:
            ok = False
            lines.append(
                f"{len(pending)} database update(s) are waiting. "
                "Close the POS and run:  .venv\\Scripts\\python.exe scripts\\setup_database.py"
            )
        lines += [f"Warning: {w}" for w in warnings]
        return HealthResult(ok, "\n".join(lines))

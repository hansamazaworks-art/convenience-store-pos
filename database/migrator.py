"""Versioned schema updates ("migrations").

Each file in migrations/versions/ is named NNNN_short_description.sql and is
applied exactly once, in number order. Applied versions are recorded in the
`schema_migrations` table, so running the updater again is always safe and
never deletes data.

Rules for writing migration files:
  * Never edit a file after it has been applied - add a new numbered file.
  * Never use DROP DATABASE. Avoid DROP TABLE except in a migration that
    first copies the data elsewhere.
  * MySQL commits automatically after CREATE/ALTER, so a migration that fails
    halfway is reported clearly and the updater stops; fix it and re-run.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from database.connection import Database, DatabaseError

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "versions"
_FILE_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INT UNSIGNED NOT NULL PRIMARY KEY,
    name        VARCHAR(150) NOT NULL,
    checksum    CHAR(64)     NOT NULL,
    applied_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def split_sql(script: str) -> list[str]:
    """Split a script into statements on ';', ignoring ';' inside quotes
    and comments ( -- ..., # ..., /* ... */ )."""
    stmts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(script)
    quote: str | None = None
    while i < n:
        c = script[i]
        nxt = script[i + 1] if i + 1 < n else ""
        if quote:
            buf.append(c)
            if c == "\\" and quote in ("'", '"'):
                buf.append(nxt)
                i += 2
                continue
            if c == quote:
                if nxt == quote:  # doubled quote escape
                    buf.append(nxt)
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if c in ("'", '"', "`"):
            quote = c
            buf.append(c)
        elif c == "-" and nxt == "-" and (i + 2 >= n or script[i + 2] in " \t\r\n"):
            while i < n and script[i] != "\n":
                i += 1
            continue
        elif c == "#":
            while i < n and script[i] != "\n":
                i += 1
            continue
        elif c == "/" and nxt == "*":
            end = script.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        elif c == ";":
            s = "".join(buf).strip()
            if s:
                stmts.append(s)
            buf = []
        else:
            buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found: dict[int, Migration] = {}
    for p in sorted(directory.glob("*.sql")):
        m = _FILE_RE.match(p.name)
        if not m:
            raise ValueError(f"Bad migration file name: {p.name} (use NNNN_name.sql)")
        v = int(m.group(1))
        if v in found:
            raise ValueError(f"Two migration files use number {v:04d}")
        found[v] = Migration(v, m.group(2), p)
    return [found[v] for v in sorted(found)]


class Migrator:
    def __init__(self, db: Database, directory: Path = MIGRATIONS_DIR) -> None:
        self.db = db
        self.directory = directory

    def ensure_table(self) -> None:
        with self.db.transaction() as cur:
            cur.execute(_CREATE_TABLE)

    def applied(self) -> dict[int, dict]:
        self.ensure_table()
        rows = self.db.fetch_all("SELECT version, name, checksum, applied_at FROM schema_migrations")
        return {int(r["version"]): r for r in rows}

    def status(self) -> tuple[list[Migration], list[Migration], list[str]]:
        """Returns (applied, pending, warnings)."""
        done = self.applied()
        all_m = discover(self.directory)
        warnings = []
        applied, pending = [], []
        for m in all_m:
            if m.version in done:
                applied.append(m)
                if done[m.version]["checksum"] != m.checksum:
                    warnings.append(
                        f"Migration {m.version:04d}_{m.name} was edited after it was applied."
                    )
            else:
                pending.append(m)
        known = {m.version for m in all_m}
        for v in done:
            if v not in known:
                warnings.append(f"Database has migration {v:04d} but its file is missing.")
        if applied and pending and pending[0].version < applied[-1].version:
            warnings.append("A lower-numbered migration is pending after newer ones were applied.")
        return applied, pending, warnings

    def migrate(self) -> list[Migration]:
        _, pending, warnings = self.status()
        for w in warnings:
            log.warning(w)
        ran = []
        for m in pending:
            log.info("Applying migration %04d_%s", m.version, m.name)
            statements = split_sql(m.sql)
            try:
                with self.db.transaction() as cur:
                    for stmt in statements:
                        cur.execute(stmt)
                    cur.execute(
                        "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s,%s,%s)",
                        (m.version, m.name, m.checksum),
                    )
            except DatabaseError as exc:
                raise DatabaseError(
                    f"Database update {m.version:04d} ({m.name}) failed. "
                    "No later updates were applied.",
                    exc.detail,
                ) from exc
            ran.append(m)
        return ran

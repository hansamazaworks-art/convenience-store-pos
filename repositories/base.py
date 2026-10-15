"""Shared helpers for repositories.

Every repository method takes an optional `cur`. Services pass the cursor of
an open transaction (db.transaction()) so several repositories can change
data together; without `cur`, a read runs on its own.
"""
from __future__ import annotations

from typing import Any, Sequence

from database.connection import Database


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _one(self, sql: str, params: Sequence[Any] = (), cur=None) -> dict | None:
        if cur is None:
            return self.db.fetch_one(sql, params)
        cur.execute(sql, params)
        row = cur.fetchone()
        cur.fetchall()
        return row

    def _all(self, sql: str, params: Sequence[Any] = (), cur=None) -> list[dict]:
        if cur is None:
            return self.db.fetch_all(sql, params)
        cur.execute(sql, params)
        return cur.fetchall()

    @staticmethod
    def _exec(cur, sql: str, params: Sequence[Any] = ()) -> int:
        cur.execute(sql, params)
        return cur.lastrowid or cur.rowcount

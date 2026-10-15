"""MySQL/MariaDB access for the whole application.

Usage (repositories/services only - the UI never touches this directly):

    db = Database(settings.db)
    rows = db.fetch_all("SELECT * FROM products WHERE barcode=%s", (code,))

    with db.transaction() as cur:          # all-or-nothing
        cur.execute("INSERT ...", (...))
        cur.execute("UPDATE ...", (...))
    # commit happens automatically; any exception -> ROLLBACK

Rules enforced here:
  * Every query is parameterized (%s placeholders) - never string formatting.
  * Every connection uses utf8mb4, strict SQL mode and READ COMMITTED.
  * A dropped connection (e.g. MySQL restarted in XAMPP) is retried once for
    read-only queries. Writes are never silently retried, to avoid double sales.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

import mysql.connector
from mysql.connector import errorcode, pooling
from mysql.connector.errors import PoolError

from config.settings import DatabaseSettings

log = logging.getLogger(__name__)

# Error numbers meaning "the connection is gone"
_CONNECTION_LOST = {
    errorcode.CR_SERVER_GONE_ERROR,      # 2006
    errorcode.CR_SERVER_LOST,            # 2013
    errorcode.CR_CONNECTION_ERROR,       # 2002
    errorcode.CR_CONN_HOST_ERROR,        # 2003
    2055,                                # Lost connection (pure-python driver)
}


class DatabaseError(Exception):
    """Error with a message a store operator can understand.
    The technical detail is kept in `.detail` and written to the log."""

    def __init__(self, user_message: str, detail: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail


def friendly_error(exc: Exception) -> DatabaseError:
    """Translate a driver error into plain language."""
    if isinstance(exc, DatabaseError):
        return exc
    errno = getattr(exc, "errno", None)
    detail = f"{type(exc).__name__}: {exc}"
    if errno in _CONNECTION_LOST:
        msg = ("Cannot reach the database.\n\n"
               "Open the XAMPP Control Panel and make sure MySQL shows a green "
               "'Running' status, then try again.")
    elif errno == errorcode.ER_ACCESS_DENIED_ERROR:
        msg = ("The database username or password is wrong.\n\n"
               "Ask the administrator to check the .env settings file.")
    elif errno == errorcode.ER_BAD_DB_ERROR:
        msg = ("The POS database does not exist yet.\n\n"
               "Run the database setup step (see docs/SETUP.md, Step 5).")
    elif errno == errorcode.ER_DUP_ENTRY:
        msg = "This record already exists (duplicate value)."
    elif errno in (errorcode.ER_ROW_IS_REFERENCED_2, errorcode.ER_ROW_IS_REFERENCED):
        msg = "This record is in use by other records and cannot be removed."
    elif errno in (errorcode.ER_NO_REFERENCED_ROW_2, errorcode.ER_NO_REFERENCED_ROW):
        msg = "A related record is missing. Please refresh and try again."
    elif errno == errorcode.ER_LOCK_WAIT_TIMEOUT or errno == errorcode.ER_LOCK_DEADLOCK:
        msg = "The database was busy. Please try again."
    elif isinstance(exc, PoolError):
        msg = "The database is busy. Please wait a moment and try again."
    else:
        msg = "A database error occurred. The details were saved to the log file."
    return DatabaseError(msg, detail)


class Database:
    def __init__(self, cfg: DatabaseSettings, *, use_database: bool = True) -> None:
        self.cfg = cfg
        self._use_database = use_database
        self._pool: pooling.MySQLConnectionPool | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ setup
    def _conn_args(self) -> dict[str, Any]:
        args: dict[str, Any] = dict(
            host=self.cfg.host,
            port=self.cfg.port,
            user=self.cfg.user,
            password=self.cfg.password,
            charset="utf8mb4",
            collation="utf8mb4_unicode_ci",
            autocommit=False,
            connection_timeout=self.cfg.connect_timeout,
            use_pure=True,
        )
        if not self.cfg.ssl:
            # XAMPP's MariaDB does not complete the TLS handshake with this
            # driver (it times out). Traffic to 127.0.0.1 never leaves the PC,
            # so encryption is off by default. Set POS_DB_SSL=on for a remote server.
            args["ssl_disabled"] = True
        if self._use_database:
            args["database"] = self.cfg.name
        return args

    def _get_pool(self) -> pooling.MySQLConnectionPool:
        with self._lock:
            if self._pool is None:
                self._pool = pooling.MySQLConnectionPool(
                    pool_name=f"pos_{id(self)}",
                    pool_size=max(1, self.cfg.pool_size),
                    pool_reset_session=True,
                    **self._conn_args(),
                )
            return self._pool

    def reset_pool(self) -> None:
        with self._lock:
            self._pool = None

    @staticmethod
    def _prepare_session(conn) -> None:
        cur = conn.cursor()
        cur.execute("SET SESSION sql_mode = 'STRICT_ALL_TABLES,NO_ZERO_DATE,"
                    "NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'")
        cur.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
        cur.execute("SET time_zone = '+08:00'")
        cur.close()

    def _borrow(self):
        """Get a pooled connection; if all are busy, wait up to ~5 seconds."""
        deadline = time.monotonic() + 5
        while True:
            try:
                return self._get_pool().get_connection()
            except PoolError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.02)

    @contextmanager
    def connection(self) -> Iterator[Any]:
        try:
            conn = self._borrow()
        except mysql.connector.Error as exc:
            if not isinstance(exc, PoolError):
                self.reset_pool()  # server problem: start fresh next time
            err = friendly_error(exc)
            log.error("DB connect failed (%s): %s", self.cfg.safe_description(), err.detail)
            raise err from exc
        try:
            try:
                conn.ping(reconnect=True, attempts=2, delay=1)
            except mysql.connector.Error as exc:
                raise friendly_error(exc) from exc
            self._prepare_session(conn)
            yield conn
        finally:
            try:
                conn.close()  # returns it to the pool
            except Exception:  # pragma: no cover
                pass

    # ------------------------------------------------------------ operations
    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """All statements inside succeed together or are all rolled back."""
        with self.connection() as conn:
            cur = conn.cursor(dictionary=True)
            try:
                conn.start_transaction()
                yield cur
                conn.commit()
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:  # pragma: no cover - connection already dead
                    pass
                if isinstance(exc, mysql.connector.Error):
                    err = friendly_error(exc)
                    log.error("Transaction rolled back: %s", err.detail)
                    raise err from exc
                log.warning("Transaction rolled back: %s", exc)
                raise
            finally:
                cur.close()

    def _read(self, sql: str, params: Sequence[Any] | dict | None, one: bool):
        for attempt in (1, 2):
            try:
                with self.connection() as conn:
                    cur = conn.cursor(dictionary=True)
                    cur.execute(sql, params or ())
                    result = cur.fetchone() if one else cur.fetchall()
                    if one:
                        cur.fetchall()  # drain any remaining rows
                    cur.close()
                    conn.rollback()  # end the read snapshot
                    return result
            except (mysql.connector.Error, DatabaseError) as exc:
                errno = getattr(exc.__cause__, "errno", getattr(exc, "errno", None))
                if attempt == 1 and errno in _CONNECTION_LOST:
                    log.warning("Connection lost during read; reconnecting once.")
                    self.reset_pool()
                    continue
                if isinstance(exc, DatabaseError):
                    raise
                err = friendly_error(exc)
                log.error("Query failed: %s", err.detail)
                raise err from exc

    def fetch_all(self, sql: str, params: Sequence[Any] | dict | None = None) -> list[dict]:
        return self._read(sql, params, one=False)

    def fetch_one(self, sql: str, params: Sequence[Any] | dict | None = None) -> dict | None:
        return self._read(sql, params, one=True)

    def execute(self, sql: str, params: Sequence[Any] | dict | None = None) -> int:
        """Single write in its own transaction. Returns lastrowid (or rowcount)."""
        with self.transaction() as cur:
            cur.execute(sql, params or ())
            return cur.lastrowid or cur.rowcount

    def server_info(self) -> dict:
        row = self.fetch_one("SELECT VERSION() AS version, DATABASE() AS db, NOW() AS now")
        return row or {}

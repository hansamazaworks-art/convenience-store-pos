"""Tests against a real MySQL/MariaDB server (skipped if not configured)."""
from decimal import Decimal

import pytest

from config.settings import DatabaseSettings
from database.connection import Database, DatabaseError
from database.migrator import Migrator
from services.system_service import SystemService

pytestmark = pytest.mark.integration


def test_connects_and_strict_mode(db):
    info = db.server_info()
    assert info["db"].startswith("pos_pytest_")
    mode = db.fetch_one("SELECT @@SESSION.sql_mode AS m")["m"]
    assert "STRICT_ALL_TABLES" in mode


def test_migrations_apply_once(db):
    m = Migrator(db)
    ran = m.migrate()
    assert [x.version for x in ran][:1] == [1]
    assert m.migrate() == []  # second run does nothing
    applied, pending, warnings = m.status()
    assert not pending and not warnings
    row = db.fetch_one("SELECT setting_value FROM app_settings WHERE setting_key=%s", ("currency_symbol",))
    assert row["setting_value"] == "₱"


def test_transaction_rolls_back_on_error(db):
    db.execute("CREATE TABLE IF NOT EXISTS tx_probe (id INT PRIMARY KEY, amt DECIMAL(12,2) NOT NULL)")
    with pytest.raises(DatabaseError):
        with db.transaction() as cur:
            cur.execute("INSERT INTO tx_probe VALUES (%s,%s)", (1, Decimal("10.50")))
            cur.execute("INSERT INTO tx_probe VALUES (%s,%s)", (1, Decimal("99.00")))  # duplicate
    assert db.fetch_one("SELECT COUNT(*) AS n FROM tx_probe")["n"] == 0

    with pytest.raises(ValueError):
        with db.transaction() as cur:
            cur.execute("INSERT INTO tx_probe VALUES (%s,%s)", (2, Decimal("1.00")))
            raise ValueError("business rule failed")
    assert db.fetch_one("SELECT COUNT(*) AS n FROM tx_probe")["n"] == 0

    with db.transaction() as cur:
        cur.execute("INSERT INTO tx_probe VALUES (%s,%s)", (3, Decimal("12.345")))
    # strict mode + DECIMAL keeps exact cents (rounded by MySQL)
    assert db.fetch_one("SELECT amt FROM tx_probe WHERE id=3")["amt"] == Decimal("12.35")


def test_parameterized_queries_block_injection(db):
    evil = "x' OR '1'='1"
    assert db.fetch_all("SELECT 1 AS one FROM DUAL WHERE %s = 'nope'", (evil,)) == []


def test_friendly_error_for_wrong_password(test_db_settings):
    bad = DatabaseSettings(**{**test_db_settings.__dict__, "password": "definitely-wrong-pw"})
    with pytest.raises(DatabaseError) as ei:
        Database(bad).server_info()
    assert "username or password" in ei.value.user_message
    assert "definitely-wrong-pw" not in ei.value.user_message


def test_friendly_error_when_server_down(test_db_settings):
    down = DatabaseSettings(**{**test_db_settings.__dict__, "port": 1, "connect_timeout": 2})
    with pytest.raises(DatabaseError) as ei:
        Database(down).server_info()
    assert "XAMPP" in ei.value.user_message


def test_reconnects_after_connection_killed(db):
    with db.connection() as conn:
        cid = conn.connection_id
    # kill the pooled connection from another session
    other = Database(db.cfg)
    try:
        other.execute(f"KILL {int(cid)}")
    except DatabaseError:
        pass
    assert db.fetch_one("SELECT 1 AS ok")["ok"] == 1


def test_system_service_health(db):
    Migrator(db).migrate()
    result = SystemService(db).check()
    assert result.ok, result.summary

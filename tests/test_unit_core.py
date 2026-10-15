"""Tests that need no database."""
from decimal import Decimal

import logging

import pytest

from config.settings import SettingsError, load_settings
from database.migrator import discover, split_sql
from utils.logging_setup import RedactSecretsFilter, setup_logging
from utils.money import MoneyError, change_due, format_money, line_total, to_money


# ---------------------------------------------------------------- money
def test_to_money_rounds_half_up():
    assert to_money("10.005") == Decimal("10.01")
    assert to_money("10.004") == Decimal("10.00")
    assert to_money(5) == Decimal("5.00")
    assert to_money("1,250.5") == Decimal("1250.50")


def test_float_rejected():
    with pytest.raises(MoneyError):
        to_money(0.1)


@pytest.mark.parametrize("bad", ["abc", "", "NaN", "Infinity", True])
def test_invalid_amounts(bad):
    with pytest.raises(MoneyError):
        to_money(bad)


def test_line_total_and_change():
    assert line_total("19.99", 3) == Decimal("59.97")
    assert line_total("12.50", Decimal("0.333")) == Decimal("4.16")
    assert change_due("187.25", "200") == Decimal("12.75")
    assert change_due("50", "50.00") == Decimal("0.00")
    with pytest.raises(MoneyError, match="short by ₱0.01"):
        change_due("50.00", "49.99")


def test_float_sum_trap_avoided():
    total = sum((to_money("0.10") for _ in range(3)), Decimal("0"))
    assert total == Decimal("0.30")


def test_format_money():
    assert format_money("1234.5") == "₱1,234.50"
    assert format_money("-3") == "-₱3.00"


# --------------------------------------------------------------- settings
def _write_env(tmp_path, body):
    p = tmp_path / ".env"
    p.write_text(body, encoding="utf-8")
    return p


def test_settings_load(tmp_path, monkeypatch):
    for k in ("POS_DB_NAME", "POS_DB_USER", "POS_DB_PASSWORD", "POS_DB_PORT"):
        monkeypatch.delenv(k, raising=False)
    env = _write_env(tmp_path, "POS_DB_USER=pos_app\nPOS_DB_PASSWORD=S3cret!\nPOS_DB_PORT=3307\n")
    s = load_settings(env)
    assert s.db.port == 3307 and s.db.name == "convenience_store_pos"
    assert "S3cret" not in repr(s.db) and "S3cret" not in s.db.safe_description()


def test_settings_missing_file(tmp_path):
    with pytest.raises(SettingsError, match="not found"):
        load_settings(tmp_path / "nope.env")


@pytest.mark.parametrize("name", ["pos;drop", "my-db", "a b", ""])
def test_settings_rejects_unsafe_db_name(tmp_path, monkeypatch, name):
    monkeypatch.delenv("POS_DB_NAME", raising=False)
    env = _write_env(tmp_path, f"POS_DB_USER=x\nPOS_DB_NAME={name}\n")
    if name == "":
        monkeypatch.setenv("POS_DB_NAME", "")
    with pytest.raises(SettingsError):
        load_settings(env)


def test_settings_bad_port(tmp_path, monkeypatch):
    monkeypatch.delenv("POS_DB_PORT", raising=False)
    env = _write_env(tmp_path, "POS_DB_USER=x\nPOS_DB_PORT=abc\n")
    with pytest.raises(SettingsError, match="whole number"):
        load_settings(env)


# ---------------------------------------------------------------- logging
def test_redaction_patterns():
    f = RedactSecretsFilter(["Hunter22"])
    assert "abc123" not in f.redact("connect password=abc123 user=root")
    assert "xyz" not in f.redact('{"pwd": "xyz"}')
    assert "Hunter22" not in f.redact("weird text Hunter22 here")
    assert "user=root" in f.redact("password=abc123 user=root")


def test_log_file_never_contains_password(tmp_path):
    setup_logging(tmp_path, "INFO", ["TopSecret99"])
    log = logging.getLogger("t")
    log.info("password=%s", "TopSecret99")
    try:
        raise RuntimeError("failed with TopSecret99")
    except RuntimeError:
        log.exception("boom")
    for h in logging.getLogger().handlers:
        h.flush()
    text = (tmp_path / "pos.log").read_text(encoding="utf-8")
    assert "TopSecret99" not in text
    assert "boom" in text


# -------------------------------------------------------------- migrations
def test_split_sql_handles_quotes_and_comments():
    script = """
    -- a comment; with semicolon
    CREATE TABLE t (a VARCHAR(10)); # another; comment
    INSERT INTO t VALUES ('x;y'), ('it''s'), ("q\\"; "); /* block ; */
    SELECT 1
    """
    stmts = split_sql(script)
    assert len(stmts) == 3
    assert "'x;y'" in stmts[1] and "it''s" in stmts[1]
    assert stmts[2] == "SELECT 1"


def test_migration_files_are_valid():
    ms = discover()
    assert ms and ms[0].version == 1
    versions = [m.version for m in ms]
    assert versions == sorted(versions) == list(range(1, len(ms) + 1))
    for m in ms:
        assert "DROP DATABASE" not in m.sql.upper()


def test_ssl_off_by_default_and_passed_to_driver(tmp_path, monkeypatch):
    from database.connection import Database
    monkeypatch.delenv("POS_DB_SSL", raising=False)
    s = load_settings(_write_env(tmp_path, "POS_DB_USER=x\n"))
    assert s.db.ssl is False
    assert Database(s.db)._conn_args()["ssl_disabled"] is True
    s2 = load_settings(_write_env(tmp_path, "POS_DB_USER=x\nPOS_DB_SSL=on\n"))
    assert "ssl_disabled" not in Database(s2.db)._conn_args()

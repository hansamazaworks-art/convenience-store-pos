"""Shared test setup.

Integration tests need a MySQL/MariaDB server and these environment
variables (they are SKIPPED if POS_TEST_DB_USER is not set):

    POS_TEST_DB_HOST (default 127.0.0.1)
    POS_TEST_DB_PORT (default 3306)
    POS_TEST_DB_USER
    POS_TEST_DB_PASSWORD

Each test run creates its own throw-away database named
pos_pytest_<random> and removes ONLY that database afterwards.
Your real POS database is never touched.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Qt's off-screen platform (used by the UI/receipt tests) does not find the
# Windows fonts by itself and draws every character as a box.
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR",
                          os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

# Test-only MySQL account made by scripts\create_test_user.py (values already
# set in the environment win).
_ENV_TEST = Path(__file__).resolve().parent.parent / ".env.test"
if _ENV_TEST.exists():
    for _line in _ENV_TEST.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from config.settings import DatabaseSettings  # noqa: E402
from database.connection import Database  # noqa: E402


@pytest.fixture(autouse=True)
def _fast_bcrypt(monkeypatch):
    """Real hashing, but with low cost so tests run fast."""
    import utils.security as sec
    monkeypatch.setattr(sec, "BCRYPT_ROUNDS", 4)


@pytest.fixture(autouse=True)
def _restore_environment():
    """load_settings() writes .env values into os.environ; undo after each test."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(scope="session")
def test_db_settings():
    user = os.environ.get("POS_TEST_DB_USER")
    if not user:
        pytest.skip("POS_TEST_DB_USER not set - skipping database tests")
    name = f"pos_pytest_{uuid.uuid4().hex[:10]}"
    cfg = DatabaseSettings(
        host=os.environ.get("POS_TEST_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("POS_TEST_DB_PORT", "3306")),
        name=name,
        user=user,
        password=os.environ.get("POS_TEST_DB_PASSWORD", ""),
        pool_size=3,
    )
    server = Database(cfg, use_database=False)
    server.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    yield cfg
    assert name.startswith("pos_pytest_")
    server.execute(f"DROP DATABASE IF EXISTS `{name}`")


@pytest.fixture()
def db(test_db_settings):
    return Database(test_db_settings)


@pytest.fixture()
def fresh_services(test_db_settings):
    """A brand-new, fully migrated database and the service container."""
    from database.migrator import Migrator
    from services.container import Services
    name = f"pos_pytest_{uuid.uuid4().hex[:10]}"
    cfg = DatabaseSettings(**{**test_db_settings.__dict__, "name": name})
    server = Database(cfg, use_database=False)
    server.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    db = Database(cfg)
    Migrator(db).migrate()
    yield Services.build(db)
    server.execute(f"DROP DATABASE IF EXISTS `{name}`")

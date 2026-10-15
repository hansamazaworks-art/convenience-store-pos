"""Backup and restore with XAMPP's mysqldump/mysql, against a throw-away pos_pytest_* database."""
import gzip
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from services.backup_service import KEEP_AUTO, BackupError, BackupService
from services.errors import PermissionDenied, ValidationError
from services.product_service import ProductInput

pytestmark = pytest.mark.integration


def _bin_dir() -> Path | None:
    raw = os.environ.get("POS_MYSQL_BIN_DIR", r"C:\xampp\mysql\bin")
    return Path(raw) if raw else None


@pytest.fixture()
def backups(fresh_services, tmp_path):
    svc = BackupService(fresh_services.db.cfg, tmp_path / "backups", _bin_dir())
    try:
        svc._tool("mysqldump")
        svc._tool("mysql")
    except BackupError:
        pytest.skip("mysqldump/mysql not found (set POS_MYSQL_BIN_DIR)")
    return svc


def test_backup_and_restore_round_trip(fresh_services, backups):
    s = fresh_services
    admin = s.auth.create_first_admin("owner", "Owner", "Owner-Pass-1")
    unit = next(u.id for u in s.catalog.list_units(admin) if u.code == "pc")
    pid = s.products.create(admin, ProductInput(name="Sardines ñ 155g", unit_id=unit, cost_price="18.50",
                                                selling_price="25", barcode="480"))
    b = backups.backup("manual")
    assert b.kind == "manual" and b.size > 0 and b.path.parent == backups.backup_dir
    assert not list(backups.backup_dir.glob("*.part"))
    with gzip.open(b.path, "rb") as f:
        dump = f.read()
    assert b"CREATE DATABASE" not in dump and b"Owner-Pass-1" not in dump and b"TRIGGER" in dump

    # change things after the backup: a new product, and the old one renamed
    s.products.create(admin, ProductInput(name="After backup", unit_id=unit, cost_price="1",
                                          selling_price="2"))
    s.db.execute("UPDATE products SET name = 'Changed' WHERE id = %s", (pid,))

    before = backups.restore(b.path)
    assert before is not None and before.kind == "before-restore"
    names = [r["name"] for r in s.db.fetch_all("SELECT name FROM products ORDER BY id")]
    assert names == ["Sardines ñ 155g"]
    assert s.db.fetch_one("SELECT cost_price FROM products")["cost_price"] == Decimal("18.50")
    # append-only triggers came back too
    from database.connection import DatabaseError
    with pytest.raises(DatabaseError):
        s.db.execute("DELETE FROM audit_log")
    # the restore can be undone with the before-restore backup
    backups.restore(before.path, safety_backup=False)
    assert {r["name"] for r in s.db.fetch_all("SELECT name FROM products")} == {"Changed", "After backup"}


def test_auto_backup_once_a_day_and_pruning(backups):
    assert backups.auto_backup_if_due() is not None
    assert backups.auto_backup_if_due() is None          # already one today
    # pretend there are many old automatic backups
    for i in range(KEEP_AUTO + 3):
        day = datetime.now() - timedelta(days=i + 1)
        (backups.backup_dir / f"{backups.cfg.name}_{day:%Y%m%d_%H%M%S}_auto.sql.gz").write_bytes(b"x")
    keep = backups.backup_dir / f"{backups.cfg.name}_20200101_000000_manual.sql.gz"
    keep.write_bytes(b"x")
    backups.backup("auto")
    autos = [b for b in backups.list_backups() if b.kind == "auto"]
    assert len(autos) == KEEP_AUTO and keep.exists()     # manual backups are never pruned


def test_backup_errors_and_permissions(fresh_services, backups, tmp_path):
    s = fresh_services
    admin = s.auth.create_first_admin("owner", "Owner", "Owner-Pass-1")
    roles = {r.code: r.id for r in s.users.list_roles(admin)}
    s.users.create_user(admin, username="boss", full_name="Boss", role_id=roles["manager"],
                        temporary_password="TempPass-1")
    with pytest.raises(PermissionDenied):
        backups.backup_now(s.auth.login("boss", "TempPass-1"))
    assert backups.backup_now(admin).kind == "manual"

    bad = BackupService(backups.cfg.__class__(**{**backups.cfg.__dict__, "password": "wrong"}),
                        tmp_path / "b2", _bin_dir())
    with pytest.raises(BackupError, match="could not be made"):
        bad.auto_backup_if_due()
    assert bad.last_error and not bad.list_backups() and not list((tmp_path / "b2").glob("*.part"))

    with pytest.raises(ValidationError):
        backups.restore(tmp_path / "missing.sql.gz")
    junk = tmp_path / "junk.sql.gz"
    with gzip.open(junk, "wb") as f:
        f.write(b"hello")
    with pytest.raises(ValidationError, match="does not look like"):
        backups.restore(junk)

"""Users, roles, permissions, login, lockout, audit (needs a test MySQL/MariaDB)."""
import uuid

import pytest

from database.migrator import Migrator
from services.audit_service import AuditService
from services.auth_service import LOCK_MINUTES, MAX_FAILED_ATTEMPTS, AuthService
from services.errors import AuthError, PermissionDenied, ValidationError
from services.settings_service import SettingsService
from services.user_service import UserService

pytestmark = pytest.mark.integration

PW = "Correct-Horse-9"


@pytest.fixture()
def fresh_db(test_db_settings):
    """A brand-new database for each test."""
    from config.settings import DatabaseSettings
    from database.connection import Database
    name = f"pos_pytest_{uuid.uuid4().hex[:10]}"
    cfg = DatabaseSettings(**{**test_db_settings.__dict__, "name": name})
    server = Database(cfg, use_database=False)
    server.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    db = Database(cfg)
    Migrator(db).migrate()
    yield db
    server.execute(f"DROP DATABASE IF EXISTS `{name}`")


@pytest.fixture()
def svc(fresh_db):
    audit = AuditService(fresh_db)
    return dict(db=fresh_db, auth=AuthService(fresh_db, audit), users=UserService(fresh_db, audit),
                settings=SettingsService(fresh_db, audit), audit=audit)


def _role_id(svc, admin, code):
    return next(r.id for r in svc["users"].list_roles(admin) if r.code == code)


def _audit_actions(db):
    return [r["action"] for r in db.fetch_all("SELECT action FROM audit_log ORDER BY id")]


# ------------------------------------------------------------- first admin
def test_first_admin_setup_only_once(svc):
    assert svc["auth"].needs_first_admin()
    admin = svc["auth"].create_first_admin("owner", "  Store   Owner ", PW)
    assert admin.role_code == "admin" and admin.full_name == "Store Owner"
    assert admin.can("users.manage") and admin.can("reports.financial")
    assert not svc["auth"].needs_first_admin()
    with pytest.raises(ValidationError, match="already exists"):
        svc["auth"].create_first_admin("owner2", "Other", PW)
    assert "user.first_admin_created" in _audit_actions(svc["db"])


def test_password_stored_hashed(svc):
    svc["auth"].create_first_admin("owner", "Owner", PW)
    h = svc["db"].fetch_one("SELECT password_hash FROM users")["password_hash"]
    assert PW not in h and h.startswith("$2")


@pytest.mark.parametrize("bad", ["short", "        ", " leading-space", "1111111111"])
def test_weak_passwords_rejected(svc, bad):
    with pytest.raises(ValidationError):
        svc["auth"].create_first_admin("owner", "Owner", bad)


@pytest.mark.parametrize("bad", ["ab", "has space", "semi;colon", ""])
def test_bad_usernames_rejected(svc, bad):
    with pytest.raises(ValidationError):
        svc["auth"].create_first_admin(bad, "Owner", PW)


# ------------------------------------------------------------------ login
def test_login_success_and_wrong_password(svc):
    svc["auth"].create_first_admin("owner", "Owner", PW)
    s = svc["auth"].login("owner", PW)
    assert s.username == "owner"
    assert svc["auth"].login("OWNER", PW).user_id == s.user_id  # usernames not case-sensitive
    with pytest.raises(AuthError, match="Wrong username or password"):
        svc["auth"].login("owner", "wrong-password")
    with pytest.raises(AuthError, match="Wrong username or password"):
        svc["auth"].login("nobody", PW)
    with pytest.raises(AuthError, match="Enter your username"):
        svc["auth"].login("", "")
    acts = _audit_actions(svc["db"])
    assert acts.count("auth.login_failed") == 2


def test_lockout_after_repeated_failures(svc):
    svc["auth"].create_first_admin("owner", "Owner", PW)
    for i in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthError) as ei:
            svc["auth"].login("owner", f"bad-pass-{i}")
    assert "locked" in ei.value.user_message
    with pytest.raises(AuthError, match="locked"):
        svc["auth"].login("owner", PW)  # even the right password is refused
    # simulate the lock expiring
    svc["db"].execute("UPDATE users SET locked_until = NOW() - INTERVAL 1 MINUTE")
    assert svc["auth"].login("owner", PW).username == "owner"
    assert LOCK_MINUTES >= 1


# ---------------------------------------------------------- user management
def test_create_user_must_change_password_and_permissions(svc):
    admin = svc["auth"].create_first_admin("owner", "Owner", PW)
    uid = svc["users"].create_user(admin, username="maria", full_name="Maria Cruz",
                                   role_id=_role_id(svc, admin, "cashier"),
                                   temporary_password="TempPass-1")
    cashier = svc["auth"].login("maria", "TempPass-1")
    assert cashier.must_change_password and cashier.user_id == uid
    assert cashier.can("pos.sell") and not cashier.can("pos.refund")
    assert not cashier.can("users.manage") and not cashier.can("reports.financial")
    with pytest.raises(PermissionDenied):
        svc["users"].list_users(cashier)
    with pytest.raises(PermissionDenied):
        svc["settings"].update(cashier, {"store_name": "Hacked"})

    cashier = svc["auth"].change_own_password(cashier, "TempPass-1", "MyOwnPass-2")
    assert not cashier.must_change_password
    with pytest.raises(AuthError):
        svc["auth"].change_own_password(cashier, "wrong-current", "Another-3x")
    assert svc["auth"].login("maria", "MyOwnPass-2").username == "maria"

    with pytest.raises(ValidationError, match="already taken"):
        svc["users"].create_user(admin, username="MARIA", full_name="X",
                                 role_id=_role_id(svc, admin, "cashier"),
                                 temporary_password="TempPass-1")


def test_disable_and_reset(svc):
    admin = svc["auth"].create_first_admin("owner", "Owner", PW)
    uid = svc["users"].create_user(admin, username="jose", full_name="Jose",
                                   role_id=_role_id(svc, admin, "inventory"),
                                   temporary_password="TempPass-1")
    svc["users"].set_active(admin, uid, False)
    with pytest.raises(AuthError, match="disabled"):
        svc["auth"].login("jose", "TempPass-1")
    svc["users"].set_active(admin, uid, True)
    # lock him out, then reset unlocks
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthError):
            svc["auth"].login("jose", "nope-nope")
    svc["users"].reset_password(admin, uid, "NewTemp-77")
    s = svc["auth"].login("jose", "NewTemp-77")
    assert s.must_change_password and s.can("inventory.adjust") and not s.can("pos.sell")


def test_last_admin_cannot_be_removed(svc):
    admin = svc["auth"].create_first_admin("owner", "Owner", PW)
    cashier_role = _role_id(svc, admin, "cashier")
    admin_role = _role_id(svc, admin, "admin")
    with pytest.raises(ValidationError, match="your own"):
        svc["users"].set_active(admin, admin.user_id, False)
    with pytest.raises(ValidationError, match="own administrator"):
        svc["users"].update_user(admin, admin.user_id, full_name="Owner", role_id=cashier_role)
    # with a second admin, the first may be demoted by the second
    uid2 = svc["users"].create_user(admin, username="admin2", full_name="Second Admin",
                                    role_id=admin_role, temporary_password="TempPass-1")
    admin2 = svc["auth"].login("admin2", "TempPass-1")
    svc["users"].update_user(admin2, admin.user_id, full_name="Owner", role_id=cashier_role)
    # now admin2 is the only admin and cannot be disabled by anyone
    with pytest.raises(ValidationError):
        svc["users"].set_active(admin2, uid2, False)


def test_manager_approval(svc):
    admin = svc["auth"].create_first_admin("owner", "Owner", PW)
    svc["users"].create_user(admin, username="boss", full_name="Manager",
                             role_id=_role_id(svc, admin, "manager"), temporary_password="Manager-01")
    svc["users"].create_user(admin, username="cash1", full_name="Cashier",
                             role_id=_role_id(svc, admin, "cashier"), temporary_password="Cashier-01")
    cashier = svc["auth"].login("cash1", "Cashier-01")
    approver = svc["auth"].approve("boss", "Manager-01", "pos.discount", "10% discount", cashier)
    assert approver.role_code == "manager"
    with pytest.raises(AuthError):
        svc["auth"].approve("boss", "wrong-pass", "pos.discount", "discount", cashier)
    with pytest.raises(PermissionDenied):  # a cashier cannot approve
        svc["auth"].approve("cash1", "Cashier-01", "pos.discount", "discount", cashier)


# ------------------------------------------------------------ settings/audit
def test_settings_update_and_audit(svc):
    admin = svc["auth"].create_first_admin("owner", "Owner", PW)
    s = svc["settings"].update(admin, {"store_name": "  Sample   Corner Store ", "currency_symbol": "S$"})
    assert s.store_name == "Sample Corner Store" and s.currency_symbol == "S$"
    with pytest.raises(ValidationError):
        svc["settings"].update(admin, {"store_name": "  "})
    with pytest.raises(ValidationError):
        svc["settings"].update(admin, {"currency_symbol": "TOOLONG"})
    rows = svc["audit"].search(admin, text="settings")
    assert rows and rows[0]["action"] == "settings.updated" and "Sample Corner" in rows[0]["details"]
    assert svc["audit"].search(admin, text="100%_") == []  # wildcards are literal


def test_audit_log_is_append_only(svc):
    from database.connection import DatabaseError
    svc["auth"].create_first_admin("owner", "Owner", PW)
    with pytest.raises(DatabaseError):
        svc["db"].execute("DELETE FROM audit_log")
    with pytest.raises(DatabaseError):
        svc["db"].execute("UPDATE audit_log SET action = 'x'")

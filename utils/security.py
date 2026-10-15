"""Password hashing with bcrypt."""
from __future__ import annotations

import bcrypt

from services.errors import ValidationError

BCRYPT_ROUNDS = 12          # ~0.2-0.3 s per check on a normal PC
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72     # bcrypt limit

# Pre-computed hash used when the username does not exist, so a wrong
# username takes as long as a wrong password (no hint which one was wrong).
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt(4))


def validate_new_password(password: str) -> None:
    if password is None or len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"The password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValidationError("The password is too long (maximum 72 characters).")
    if password.strip() != password:
        raise ValidationError("The password cannot start or end with a space.")
    if password.isdigit() and len(set(password)) == 1:
        raise ValidationError("The password is too simple.")


def hash_password(password: str) -> str:
    validate_new_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    raw = (password or "").encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raw = raw[:MAX_PASSWORD_BYTES]
    try:
        if not password_hash:
            bcrypt.checkpw(raw, _DUMMY_HASH)
            return False
        return bcrypt.checkpw(raw, password_hash.encode("ascii"))
    except ValueError:
        return False


def burn_time() -> None:
    """Spend the same time as a real check (used for unknown usernames)."""
    verify_password("x", None)

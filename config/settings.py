"""Application settings loaded from the .env file.

The .env file holds the database password, so it is listed in .gitignore
and must never be shared. Use .env.example as the template.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def app_root() -> Path:
    """Folder that holds .env, logs/ and backups/.

    When packaged with PyInstaller (sys.frozen), this is the folder of the .exe;
    otherwise it is the project folder.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str) -> Path:
    """Path to a bundled file (icons...). Works from source and from the .exe."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


class SettingsError(Exception):
    """Raised when the .env configuration is missing or invalid."""


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    name: str
    user: str
    password: str = field(repr=False)  # never printed
    pool_size: int = 5
    connect_timeout: int = 5
    ssl: bool = False

    def safe_description(self) -> str:
        """Description safe for logs and screens (no password)."""
        return f"{self.user}@{self.host}:{self.port}/{self.name}"


@dataclass(frozen=True)
class Settings:
    db: DatabaseSettings
    store_name: str
    currency_symbol: str
    log_level: str
    log_dir: Path
    backup_dir: Path
    mysql_bin_dir: Path | None
    root: Path


def _get_int(key: str, default: int) -> int:
    raw = os.environ.get(key, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise SettingsError(f"{key} must be a whole number (got '{raw}').") from exc


def load_settings(env_file: Path | None = None) -> Settings:
    root = app_root()
    env_path = env_file or root / ".env"
    if not env_path.exists():
        raise SettingsError(
            f"Configuration file not found: {env_path}\n"
            "Copy .env.example to .env and fill in your MySQL details."
        )
    load_dotenv(env_path, override=True)

    name = os.environ.get("POS_DB_NAME", "convenience_store_pos").strip()
    if not _DB_NAME_RE.match(name):
        raise SettingsError(
            "POS_DB_NAME may only contain letters, numbers and underscores."
        )
    user = os.environ.get("POS_DB_USER", "").strip()
    if not user:
        raise SettingsError("POS_DB_USER is empty in .env.")

    db = DatabaseSettings(
        host=os.environ.get("POS_DB_HOST", "127.0.0.1").strip(),
        port=_get_int("POS_DB_PORT", 3306),
        name=name,
        user=user,
        # Empty password is allowed only if the user deliberately leaves it blank.
        password=os.environ.get("POS_DB_PASSWORD", ""),
        pool_size=_get_int("POS_DB_POOL_SIZE", 5),
        connect_timeout=_get_int("POS_DB_CONNECT_TIMEOUT", 5),
        ssl=os.environ.get("POS_DB_SSL", "off").strip().lower() in ("on", "true", "1", "yes"),
    )

    def _dir(key: str, default: str) -> Path:
        p = Path(os.environ.get(key, default))
        return p if p.is_absolute() else root / p

    bin_raw = os.environ.get("POS_MYSQL_BIN_DIR", "").strip()
    return Settings(
        db=db,
        store_name=os.environ.get("POS_STORE_NAME", "My Convenience Store").strip(),
        currency_symbol=os.environ.get("POS_CURRENCY_SYMBOL", "₱").strip() or "₱",
        log_level=os.environ.get("POS_LOG_LEVEL", "INFO").strip().upper(),
        log_dir=_dir("POS_LOG_DIR", "logs"),
        backup_dir=_dir("POS_BACKUP_DIR", "backups"),
        mysql_bin_dir=Path(bin_raw) if bin_raw else None,
        root=root,
    )

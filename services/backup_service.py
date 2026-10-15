"""Database backups (mysqldump) and restore (mysql), using XAMPP's own tools.

- A backup is one gzip-compressed SQL file in the backups folder:
  `<db>_YYYYMMDD_HHMMSS_<kind>.sql.gz` (kind = auto, manual, before-restore).
  It is written to a temporary name first and renamed only when mysqldump finished
  correctly, so a half-written file never looks like a good backup.
- The dump has no CREATE DATABASE line, so it can be restored into any database
  (the tests restore into a throw-away pos_pytest_* database).
- The password is passed in a temporary option file, never on the command line
  (other programs can see command lines), and the file is deleted straight away.
- One automatic backup per day (`auto_backup_if_due`, called when the POS starts);
  the newest 30 automatic backups are kept. Manual and before-restore backups are never
  deleted by the program.
- Restore (scripts/restore_backup.py only, never from the POS screens) first makes a
  "before-restore" backup of the current data, so a wrong restore can be undone.
"""
from __future__ import annotations

import re
import gzip
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config.settings import DatabaseSettings
from models.user import Session
from services.errors import ServiceError, ValidationError

log = logging.getLogger(__name__)

KEEP_AUTO = 30
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # no black console window on Windows


class BackupError(ServiceError):
    """A backup or restore could not be made."""


@dataclass(frozen=True)
class BackupFile:
    path: Path
    created: datetime
    kind: str
    size: int

    @property
    def name(self) -> str:
        return self.path.name


def _option_file(cfg: DatabaseSettings) -> str:
    """Temporary [client] option file with the login (deleted by the caller)."""
    pw = cfg.password.replace("\\", "\\\\").replace('"', '\\"')
    fd, name = tempfile.mkstemp(prefix="pos_", suffix=".cnf")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f'[client]\nuser="{cfg.user}"\npassword="{pw}"\nhost="{cfg.host}"\nport={cfg.port}\n')
    return name


class BackupService:
    def __init__(self, cfg: DatabaseSettings, backup_dir: Path, mysql_bin_dir: Path | None = None) -> None:
        self.cfg = cfg
        self.backup_dir = Path(backup_dir)
        self.mysql_bin_dir = mysql_bin_dir
        self.last_error = ""        # message of the last failed automatic backup ("" = fine)

    # ----------------------------------------------------------------- tools
    def _tool(self, name: str) -> str:
        exe = name + (".exe" if os.name == "nt" else "")
        candidates = [self.mysql_bin_dir / exe] if self.mysql_bin_dir else []
        candidates.append(Path(r"C:\xampp\mysql\bin") / exe)
        for c in candidates:
            if c.is_file():
                return str(c)
        found = shutil.which(name)
        if found:
            return found
        raise BackupError(f"The MySQL tool '{exe}' was not found. Set POS_MYSQL_BIN_DIR in the .env file "
                          r"to XAMPP's mysql\bin folder (for example C:\xampp\mysql\bin).")

    # ----------------------------------------------------------------- reads
    def list_backups(self) -> list[BackupFile]:
        """Newest first."""
        if not self.backup_dir.is_dir():
            return []
        out = []
        for p in self.backup_dir.glob(f"{self.cfg.name}_*.sql.gz"):
            parts = p.name[len(self.cfg.name) + 1:-len(".sql.gz")].split("_", 2)
            try:
                created = datetime.strptime(parts[0] + parts[1], "%Y%m%d%H%M%S")
            except (ValueError, IndexError):
                continue
            kind = re.sub(r"-\d+$", "", parts[2]) if len(parts) > 2 else ""   # "auto-2" -> "auto"
            out.append(BackupFile(p, created, kind, p.stat().st_size))
        return sorted(out, key=lambda b: (b.created, b.name), reverse=True)

    def last_backup(self) -> BackupFile | None:
        files = self.list_backups()
        return files[0] if files else None

    # ---------------------------------------------------------------- backup
    def backup(self, kind: str = "manual") -> BackupFile:
        if kind not in ("auto", "manual", "before-restore"):
            raise ValidationError("Unknown backup kind.")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        final = self.backup_dir / f"{self.cfg.name}_{now:%Y%m%d_%H%M%S}_{kind}.sql.gz"
        n = 1
        while final.exists():                       # two backups in the same second
            n += 1
            final = self.backup_dir / f"{self.cfg.name}_{now:%Y%m%d_%H%M%S}_{kind}-{n}.sql.gz"
        tmp = final.with_name(final.name + ".part")
        opt = _option_file(self.cfg)
        try:
            cmd = [self._tool("mysqldump"), f"--defaults-extra-file={opt}", "--single-transaction",
                   "--routines", "--triggers", "--hex-blob", "--default-character-set=utf8mb4",
                   "--skip-comments", "--add-drop-table", self.cfg.name]
            with gzip.open(tmp, "wb") as out, tempfile.TemporaryFile() as errf:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf,
                                        creationflags=_NO_WINDOW)
                tail = b""
                for chunk in iter(lambda: proc.stdout.read(1 << 16), b""):
                    out.write(chunk)
                    tail = (tail + chunk)[-200:]
                code = proc.wait()
                errf.seek(0)
                err = errf.read().decode("utf-8", "replace").strip()
            # --skip-comments also drops the final "Dump completed" line, so check the exit code
            # and that the dump ends with the session settings it restores at the end.
            if code != 0 or b"SET SQL_NOTES=@OLD_SQL_NOTES" not in tail:
                log.error("mysqldump failed (exit %s): %s", code, err[:500])
                raise BackupError("The backup could not be made. Is MySQL running in XAMPP? "
                                  "Details were saved to logs\\pos.log.")
            tmp.replace(final)
        except OSError as exc:
            log.error("Backup failed: %s", exc)
            raise BackupError(f"The backup could not be saved ({exc.strerror or exc}).") from None
        finally:
            os.unlink(opt)
            if tmp.exists():
                tmp.unlink()
        self.last_error = ""
        log.info("Backup saved: %s (%d bytes)", final.name, final.stat().st_size)
        if kind == "auto":
            self._prune()
        return next(b for b in self.list_backups() if b.path == final)

    def backup_now(self, session: Session) -> BackupFile:
        session.require("settings.manage", "make a backup")
        return self.backup("manual")

    def auto_backup_if_due(self) -> BackupFile | None:
        """Make the daily backup if none was made today. Returns it, or None if not due."""
        today = datetime.now().date()
        if any(b.created.date() == today for b in self.list_backups()):
            return None
        try:
            made = self.backup("auto")
        except Exception as exc:
            self.last_error = getattr(exc, "user_message", "The automatic backup failed. "
                                                           "Details are in logs\\pos.log.")
            raise
        self.last_error = ""
        return made

    def _prune(self) -> None:
        autos = [b for b in self.list_backups() if b.kind.startswith("auto")]
        for old in autos[KEEP_AUTO:]:
            try:
                old.path.unlink()
                log.info("Old automatic backup removed: %s", old.name)
            except OSError as exc:
                log.warning("Could not remove old backup %s: %s", old.name, exc)

    # --------------------------------------------------------------- restore
    def restore(self, backup: Path, *, safety_backup: bool = True) -> BackupFile | None:
        """Replace the database contents with the backup. Makes a before-restore backup first
        (returned), so this can be undone by restoring that file."""
        backup = Path(backup)
        if not backup.is_file() or not backup.name.endswith(".sql.gz"):
            raise ValidationError("Choose a backup file (.sql.gz) from the backups folder.")
        try:
            with gzip.open(backup, "rb") as f:
                head = f.read(4096)
        except OSError:
            raise ValidationError("This file is not a readable backup.") from None
        if b"CREATE TABLE" not in head and b"DROP TABLE" not in head:
            raise ValidationError("This file does not look like a POS backup.")
        before = self.backup("before-restore") if safety_backup else None
        opt = _option_file(self.cfg)
        try:
            with tempfile.TemporaryFile() as errf:
                proc = subprocess.Popen([self._tool("mysql"), f"--defaults-extra-file={opt}",
                                         "--default-character-set=utf8mb4", self.cfg.name],
                                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errf,
                                        creationflags=_NO_WINDOW)
                with gzip.open(backup, "rb") as f:
                    try:
                        shutil.copyfileobj(f, proc.stdin, 1 << 16)
                    except BrokenPipeError:       # mysql stopped early; its error is in errf
                        pass
                    finally:
                        try:
                            proc.stdin.close()
                        except BrokenPipeError:
                            pass
                code = proc.wait()
                errf.seek(0)
                err = errf.read().decode("utf-8", "replace").strip()
        finally:
            os.unlink(opt)
        if code != 0:
            log.error("Restore of %s failed (exit %s): %s", backup.name, code, err[:500])
            raise BackupError("The restore failed. Your data before the restore was saved as "
                              f"{before.name if before else 'nothing'}. Details are in logs\\pos.log.")
        log.warning("Database %s restored from %s", self.cfg.name, backup.name)
        return before

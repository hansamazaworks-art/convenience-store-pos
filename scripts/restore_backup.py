"""
Make a backup, list backups, or put a backup back (restore).

Run from Command Prompt inside the project folder, with the POS CLOSED:
    .venv\\Scripts\\python.exe scripts\\restore_backup.py --list       # show the backups
    .venv\\Scripts\\python.exe scripts\\restore_backup.py --backup     # make a backup now
    .venv\\Scripts\\python.exe scripts\\restore_backup.py --restore    # choose one and restore it

Restore REPLACES all data in the POS database with the data in the backup.
Before it does, it saves the current data as a "before-restore" backup, so a
wrong restore can be undone by restoring that file. You must type RESTORE to confirm.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import SettingsError, load_settings  # noqa: E402
from services.backup_service import BackupService  # noqa: E402
from services.errors import ServiceError  # noqa: E402
from utils.logging_setup import setup_logging  # noqa: E402


def _show(files) -> None:
    if not files:
        print("No backups found.")
    for i, b in enumerate(files, 1):
        print(f"{i:>3}. {b.created:%d %b %Y %H:%M:%S}  {b.kind:<15} {b.size / 1024:>9,.0f} KB  {b.name}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="list backups")
    g.add_argument("--backup", action="store_true", help="make a backup now")
    g.add_argument("--restore", nargs="?", const="", metavar="FILE",
                   help="restore a backup (asks which one if FILE is not given)")
    args = ap.parse_args(argv)
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"CONFIGURATION PROBLEM:\n{exc}")
        return 2
    setup_logging(settings.log_dir, settings.log_level, [settings.db.password])
    svc = BackupService(settings.db, settings.backup_dir, settings.mysql_bin_dir)
    print(f"Database: {settings.db.name}    Backups folder: {svc.backup_dir}\n")
    try:
        if args.list:
            _show(svc.list_backups())
            return 0
        if args.backup:
            b = svc.backup("manual")
            print(f"Backup saved: {b.path}")
            return 0
        # --restore
        files = svc.list_backups()
        if args.restore:
            chosen = Path(args.restore)
            if not chosen.is_absolute() and not chosen.exists():
                chosen = svc.backup_dir / chosen
        else:
            _show(files)
            if not files:
                return 1
            pick = input("\nNumber of the backup to restore (Enter = cancel): ").strip()
            if not pick.isdigit() or not 1 <= int(pick) <= len(files):
                print("Cancelled. Nothing was changed.")
                return 1
            chosen = files[int(pick) - 1].path
        print(f"\nThis will REPLACE ALL DATA in database '{settings.db.name}' with:\n  {chosen}")
        print("Close the POS on every computer first. Your current data will be saved first.")
        if input("Type RESTORE to continue: ").strip() != "RESTORE":
            print("Cancelled. Nothing was changed.")
            return 1
        before = svc.restore(chosen)
        print(f"\nRestored. Your data from just before the restore was saved as:\n  {before.path}")
        print("Now run scripts\\setup_database.py (applies any newer updates), then start the POS.")
        return 0
    except ServiceError as exc:
        print(f"\nPROBLEM: {exc.user_message}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

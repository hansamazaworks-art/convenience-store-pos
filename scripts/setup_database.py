"""
Create the POS database (if missing) and apply schema updates.

Run from PowerShell inside the project folder:
    python scripts\\setup_database.py            # create DB if needed + apply updates
    python scripts\\setup_database.py --status   # only show what would happen

Safety:
  * Never drops or empties any database or table.
  * If a database with the configured name already exists but was NOT
    created by this POS (no schema_migrations table, but other tables),
    the script STOPS and changes nothing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import SettingsError, load_settings  # noqa: E402
from database.connection import Database, DatabaseError  # noqa: E402
from database.migrator import Migrator  # noqa: E402
from utils.logging_setup import setup_logging  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="show status only, change nothing")
    args = ap.parse_args(argv)

    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"CONFIGURATION PROBLEM:\n{exc}")
        return 2
    setup_logging(settings.log_dir, settings.log_level, [settings.db.password])
    name = settings.db.name
    print(f"Database server : {settings.db.host}:{settings.db.port}")
    print(f"Database name   : {name}")

    server = Database(settings.db, use_database=False)
    try:
        exists = server.fetch_one(
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (name,)
        )
        if exists:
            tables = {r["TABLE_NAME"] for r in server.fetch_all(
                "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s", (name,))}
            if tables and "schema_migrations" not in tables:
                print(f"\nSTOPPED: database '{name}' already exists and contains "
                      f"{len(tables)} table(s) that were NOT created by this POS:")
                for t in sorted(tables)[:20]:
                    print(f"   - {t}")
                print("\nNothing was changed. Choose a different POS_DB_NAME in .env, "
                      "or ask your support person about this database.")
                return 3
            print(f"Database '{name}' exists ({len(tables)} tables).")
        else:
            if args.status:
                print(f"Database '{name}' does not exist yet (would be created).")
                return 0
            server.execute(
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )  # name is validated in settings (letters/numbers/underscore only)
            print(f"Created database '{name}'.")

        migrator = Migrator(Database(settings.db))
        if args.status:
            applied, pending, warnings = migrator.status()
            print(f"Applied updates : {len(applied)}")
            print(f"Pending updates : {len(pending)}")
            for m in pending:
                print(f"   - {m.version:04d}_{m.name}")
            for w in warnings:
                print(f"WARNING: {w}")
            return 0

        ran = migrator.migrate()
        if ran:
            for m in ran:
                print(f"Applied update {m.version:04d}_{m.name}")
        else:
            print("Database is already up to date.")
        print("\nSUCCESS.")
        return 0
    except DatabaseError as exc:
        print(f"\nPROBLEM: {exc.user_message}")
        if exc.detail:
            print(f"(technical detail: {exc.detail})")
        return 1


if __name__ == "__main__":
    sys.exit(main())

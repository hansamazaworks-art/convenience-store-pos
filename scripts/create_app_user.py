"""
Create a dedicated MySQL account for the POS (recommended instead of root)
and save its details into .env.

Run from PowerShell inside the project folder:
    python scripts\\create_app_user.py

You will be asked for:
  1. An ADMIN MySQL account (usually 'root') and its password
     (press Enter if root has no password). Used once, never saved.
  2. A NEW password for the POS account 'pos_app'.

The new account can only access the POS database - nothing else.
"""
from __future__ import annotations

import getpass
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mysql.connector  # noqa: E402

from config.settings import app_root  # noqa: E402

ROOT = app_root()   # project folder, or the folder of the .exe
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"


def set_env_values(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in values and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={values[key]}"
            seen.add(key)
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if not ENV.exists():
        ENV.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        print("Created .env from .env.example")

    db_name = input("POS database name [convenience_store_pos]: ").strip() or "convenience_store_pos"
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", db_name):
        print("Name may only contain letters, numbers and underscores.")
        return 2
    host = input("MySQL host [127.0.0.1]: ").strip() or "127.0.0.1"
    port = int(input("MySQL port [3306]: ").strip() or "3306")
    admin = input("Admin MySQL username [root]: ").strip() or "root"
    print("Admin password (press Enter if it has none). Typing is invisible.")
    admin_pw = getpass.getpass("Admin password: ")

    while True:
        new_pw = getpass.getpass("NEW password for 'pos_app' (min 8 characters): ")
        if len(new_pw) < 8:
            print("Too short, try again.")
            continue
        if new_pw != getpass.getpass("Type it again: "):
            print("They do not match, try again.")
            continue
        break

    try:
        conn = mysql.connector.connect(
            host=host, port=port, user=admin, password=admin_pw,
            ssl_disabled=True, use_pure=True, connection_timeout=10,
        )
    except mysql.connector.Error as exc:
        print(f"Could not log in as {admin}: {getattr(exc, 'msg', exc)}")
        return 1
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM mysql.user WHERE User='pos_app'")
    if cur.fetchone()[0]:
        ans = input("Account 'pos_app' already exists. Change its password? (y/n): ").strip().lower()
        if ans != "y":
            print("Nothing changed.")
            return 0
    for h in ("localhost", "127.0.0.1"):
        cur.execute("CREATE USER IF NOT EXISTS 'pos_app'@%s IDENTIFIED BY %s", (h, new_pw))
        cur.execute("ALTER USER 'pos_app'@%s IDENTIFIED BY %s", (h, new_pw))
        # CREATE privilege on this one DB lets setup_database.py create it.
        cur.execute(f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO 'pos_app'@%s", (h,))
    cur.execute("FLUSH PRIVILEGES")
    conn.commit()
    conn.close()

    set_env_values(ENV, {
        "POS_DB_HOST": host, "POS_DB_PORT": str(port), "POS_DB_NAME": db_name,
        "POS_DB_USER": "pos_app", "POS_DB_PASSWORD": new_pw,
    })
    print(f"\nDone. Account 'pos_app' can access only '{db_name}'.")
    print("Its details were saved in .env (keep that file private).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Create a MySQL account used ONLY by the automatic tests (pytest).

Run from Command Prompt inside the project folder:
    .venv\\Scripts\\python.exe scripts\\create_test_user.py

You type the XAMPP root password once (invisible, never saved). The script
creates the account 'pos_test' with a random password and saves it in
.env.test (private, like .env). That account can only create, use and delete
databases whose names start with pos_pytest_ - it cannot see or change the
real POS database.
"""
from __future__ import annotations

import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mysql.connector  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENV_TEST = ROOT / ".env.test"
USER = "pos_test"


def main() -> int:
    host = input("MySQL host [127.0.0.1]: ").strip() or "127.0.0.1"
    port = int(input("MySQL port [3306]: ").strip() or "3306")
    admin = input("Admin MySQL username [root]: ").strip() or "root"
    print("Admin password (press Enter if it has none). Typing is invisible.")
    admin_pw = getpass.getpass("Admin password: ")
    try:
        conn = mysql.connector.connect(host=host, port=port, user=admin, password=admin_pw,
                                       ssl_disabled=True, use_pure=True, connection_timeout=10)
    except mysql.connector.Error as exc:
        print(f"Could not log in as {admin}: {getattr(exc, 'msg', exc)}")
        return 1
    new_pw = secrets.token_urlsafe(18)
    cur = conn.cursor()
    for h in ("localhost", "127.0.0.1"):
        cur.execute(f"CREATE USER IF NOT EXISTS '{USER}'@%s IDENTIFIED BY %s", (h, new_pw))
        cur.execute(f"ALTER USER '{USER}'@%s IDENTIFIED BY %s", (h, new_pw))
        # Only databases named pos_pytest_... (the backslashes make '_' literal).
        cur.execute(f"GRANT ALL PRIVILEGES ON `pos\\_pytest\\_%`.* TO '{USER}'@%s", (h,))
    cur.execute("FLUSH PRIVILEGES")
    conn.commit()
    conn.close()
    ENV_TEST.write_text(
        "# Test-only MySQL account (created by scripts\\create_test_user.py). Keep private.\n"
        f"POS_TEST_DB_HOST={host}\nPOS_TEST_DB_PORT={port}\n"
        f"POS_TEST_DB_USER={USER}\nPOS_TEST_DB_PASSWORD={new_pw}\n", encoding="utf-8")
    print(f"\nDone. Account '{USER}' can only use databases named pos_pytest_...")
    print("Its details were saved in .env.test. Tests now run with:")
    print("    .venv\\Scripts\\python.exe -m pytest")
    return 0


if __name__ == "__main__":
    sys.exit(main())

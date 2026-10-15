"""
PHASE 0 - Environment check (READ-ONLY).

This script only LOOKS at your computer. It does not install, create,
change, or delete anything.

Run from PowerShell inside the project folder:
    python scripts\\check_environment.py

It checks:
  1. Python version
  2. Required Python packages
  3. XAMPP installation folder
  4. Whether MySQL/MariaDB is listening on its port
  5. (Optional) Logs in to MySQL and lists existing databases

The MySQL password you type is NOT shown on screen, NOT saved, and NOT logged.
At the end it writes a report to scripts\\environment_report.txt
(the report never contains your password). Keep that report for troubleshooting.
"""
from __future__ import annotations

import getpass
import importlib
import os
import platform
import socket
import sys
from pathlib import Path

# Project folder, or the folder of the .exe when packaged.
ROOT = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent.parent)

REPORT_LINES: list[str] = []

REQUIRED_PACKAGES = {
    "PySide6": "PySide6",
    "mysql.connector": "mysql-connector-python",
    "dotenv": "python-dotenv",
    "bcrypt": "bcrypt",
    "pytest": "pytest",
    "reportlab": "reportlab",
    "PyInstaller": "pyinstaller",
}

XAMPP_CANDIDATES = [Path(r"C:\xampp"), Path(r"D:\xampp"), Path(r"C:\Program Files\xampp")]


def out(line: str = "") -> None:
    print(line)
    REPORT_LINES.append(line)


def section(title: str) -> None:
    out()
    out("=" * 60)
    out(title)
    out("=" * 60)


def check_python() -> None:
    section("1. PYTHON")
    out(f"Python version : {platform.python_version()}")
    out(f"Python program : {sys.executable}")
    out(f"Operating sys. : {platform.platform()}")
    if sys.version_info < (3, 10):
        out("RESULT: PROBLEM - Python 3.10 or newer is required.")
    else:
        out("RESULT: OK")


def check_packages() -> list[str]:
    section("2. PYTHON PACKAGES")
    missing = []
    if getattr(sys, "frozen", False):
        out("Packaged program: the packages are built in (no Python needed).")
        return missing
    for module, pip_name in REQUIRED_PACKAGES.items():
        try:
            mod = importlib.import_module(module)
            version = getattr(mod, "__version__", "installed")
            out(f"  [OK]      {pip_name:<25} {version}")
        except Exception:
            out(f"  [MISSING] {pip_name}")
            missing.append(pip_name)
    if missing:
        out("RESULT: Some packages are missing (normal at this stage).")
        out("        They will be installed in Phase 1 with: pip install -r requirements.txt")
    else:
        out("RESULT: OK - all packages present")
    return missing


def find_xampp() -> Path | None:
    section("3. XAMPP")
    for p in XAMPP_CANDIDATES:
        if p.exists():
            out(f"XAMPP folder found: {p}")
            mysql_bin = p / "mysql" / "bin"
            for exe in ("mysql.exe", "mysqldump.exe", "mysqld.exe"):
                status = "found" if (mysql_bin / exe).exists() else "NOT found"
                out(f"  {exe:<15} {status}")
            ini = p / "mysql" / "bin" / "my.ini"
            if ini.exists():
                for raw in ini.read_text(errors="ignore").splitlines():
                    s = raw.strip().lower().replace(" ", "")
                    if s.startswith("port="):
                        out(f"  my.ini port setting: {raw.strip()}")
                        break
            return p
    out("XAMPP folder NOT found in the usual places (C:\\xampp, D:\\xampp).")
    out("RESULT: Check where XAMPP is installed.")
    return None


def check_port(host: str, port: int) -> bool:
    section("4. MYSQL SERVER (is it running?)")
    try:
        with socket.create_connection((host, port), timeout=3) as s:
            out(f"Something is listening on {host}:{port}  -> MySQL appears to be RUNNING")
            # The server's first message (sent before any login) includes its version.
            try:
                s.settimeout(3)
                data = s.recv(256)
                if len(data) > 5 and data[4] == 10:
                    version = data[5:data.index(b"\x00", 5)].decode("ascii", "replace")
                    out(f"Server reports version: {version}")
                elif len(data) > 7 and data[4] == 0xFF:
                    out("Server refused this computer: "
                        + data[7:].decode("utf-8", "replace"))
            except (OSError, ValueError):
                out("(Could not read the server version.)")
            return True
    except OSError:
        out(f"Nothing is listening on {host}:{port}")
        out("RESULT: MySQL is NOT running. Open the XAMPP Control Panel and click")
        out("        'Start' next to MySQL, then run this script again.")
        return False


def inspect_mysql(host: str, port: int) -> None:
    section("5. MYSQL LOGIN AND EXISTING DATABASES (read-only)")
    try:
        import mysql.connector  # type: ignore
    except ImportError:
        out("Skipped: mysql-connector-python is not installed yet.")
        out("Install it with:  python -m pip install mysql-connector-python")
        out("Then run this script again.")
        return

    answer = input("\nTry logging in to MySQL to list databases? (y/n): ").strip().lower()
    if answer != "y":
        out("Skipped by user.")
        return

    user = input("MySQL username [root]: ").strip() or "root"
    out(f"Username used: {user}")
    print("MySQL password (just press Enter if the account has NO password).")
    print("Your typing will be invisible - that is normal.")
    password = getpass.getpass("Password: ")
    out(f"Password provided: {'yes' if password else 'no (empty)'}")

    try:
        # ssl_disabled: XAMPP's MariaDB does not complete the TLS handshake with
        # this driver; local traffic never leaves the computer.
        conn = mysql.connector.connect(
            host=host, port=port, user=user, password=password,
            connection_timeout=10, ssl_disabled=True, use_pure=True,
        )
    except mysql.connector.Error as exc:
        out(f"LOGIN FAILED: {getattr(exc, 'msg', None) or exc}")
        if getattr(exc, "errno", None) == 1045:
            out("RESULT: The username or password is wrong.")
        elif getattr(exc, "errno", None) == 1130:
            out("RESULT: This account is not allowed to connect from 127.0.0.1.")
        else:
            out("RESULT: Could not complete the connection (not a password problem).")
            out(f"        Error number: {getattr(exc, 'errno', 'unknown')}")
        return
    finally:
        password = ""  # discard

    cur = conn.cursor()
    cur.execute("SELECT VERSION()")
    out(f"Server version: {cur.fetchone()[0]}")
    cur.execute("SELECT @@character_set_server, @@collation_server, @@sql_mode")
    cs, coll, mode = cur.fetchone()
    out(f"Charset/collation: {cs} / {coll}")
    out(f"SQL mode: {mode}")

    cur.execute("SHOW DATABASES")
    system_dbs = {"information_schema", "mysql", "performance_schema", "sys", "phpmyadmin", "test"}
    dbs = [r[0] for r in cur.fetchall()]
    user_dbs = [d for d in dbs if d.lower() not in system_dbs]
    out(f"All databases: {', '.join(dbs)}")
    out(f"Your own (non-system) databases: {', '.join(user_dbs) or '(none)'}")

    for db in user_dbs:
        cur.execute(
            "SELECT TABLE_NAME, TABLE_ROWS FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
            (db,),
        )
        rows = cur.fetchall()
        out(f"\n  Database '{db}' has {len(rows)} table(s):")
        for name, approx_rows in rows[:40]:
            out(f"     - {name}  (~{approx_rows} rows)")
        if len(rows) > 40:
            out(f"     ... and {len(rows) - 40} more")
    cur.close()
    conn.close()
    out("\nRESULT: MySQL login OK. Nothing was changed.")


def check_project_folder() -> None:
    section("6. PROJECT FOLDER")
    here = ROOT
    out(f"Project folder: {here}")
    env = here / ".env"
    out(f".env file present: {'yes' if env.exists() else 'no'}")


def main() -> None:
    out("CONVENIENCE STORE POS - PHASE 0 ENVIRONMENT CHECK (read-only)")
    check_python()
    check_packages()
    find_xampp()
    host = os.environ.get("POS_DB_HOST", "127.0.0.1")
    port = int(os.environ.get("POS_DB_PORT", "3306"))
    if check_port(host, port):
        inspect_mysql(host, port)
    check_project_folder()

    report = (ROOT if getattr(sys, "frozen", False) else Path(__file__).resolve().parent) \
        / "environment_report.txt"
    report.write_text("\n".join(REPORT_LINES), encoding="utf-8")
    print(f"\nReport saved to: {report}")
    print("Keep that file for troubleshooting.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")

"""POS Tools - setup and maintenance menu (console).

Packaged as "POS Tools.exe" next to the POS program, so the store PC can be set
up and backed up without Python. From the project folder it also runs as:
    .venv\\Scripts\\python.exe pos_tools.py
"""
from __future__ import annotations

import sys

MENU = """
==============================================
  POS TOOLS
==============================================
  1. Check this computer (read-only report)
  2. Create the POS database account (pos_app)
  3. Create / update the POS database
  4. Show database status (changes nothing)
  5. Make a backup now
  6. List backups
  7. Restore a backup
  0. Exit
"""


def _run(choice: str) -> None:
    if choice == "1":
        from scripts import check_environment
        check_environment.main()
    elif choice == "2":
        from scripts import create_app_user
        create_app_user.main()
    elif choice in ("3", "4"):
        from scripts import setup_database
        setup_database.main(["--status"] if choice == "4" else [])
    elif choice in ("5", "6", "7"):
        from scripts import restore_backup
        restore_backup.main([{"5": "--backup", "6": "--list", "7": "--restore"}[choice]])


def main() -> int:
    while True:
        print(MENU)
        try:
            choice = input("Choose a number: ").strip()
        except EOFError:
            return 0
        if choice == "0":
            return 0
        if len(choice) != 1 or choice not in "1234567":
            print("Please type a number from the list.")
            continue
        try:
            _run(choice)
        except KeyboardInterrupt:
            print("\nStopped.")
        except SystemExit:
            pass
        except Exception as exc:  # noqa: BLE001 - keep the menu open and say what happened
            print(f"\nPROBLEM: {exc}")
        try:
            input("\nPress Enter to go back to the menu...")
        except EOFError:
            return 0


if __name__ == "__main__":
    sys.exit(main())

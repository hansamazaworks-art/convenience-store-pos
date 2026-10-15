# Architecture

## Layers (top calls down, never up)

```
ui/            PySide6 windows, pages, dialogs, widgets — display + user input only
  ↓
services/      business rules (pricing, permissions, sale completion, costing)
  ↓
repositories/  all SQL for one area (products, sales, stock...) — parameterized only
  ↓
database/      connection pool, transactions, reconnect, migrations
```
Plus: `config/` (settings from `.env`), `utils/` (money, logging), `models/`
(plain dataclasses passed between layers), `reports/` (CSV/PDF), `scripts/`
(setup/maintenance tools run from PowerShell).

**Rule:** the UI never imports `database` or writes SQL. A service method that
changes several tables does it inside **one** `db.transaction()`.

## Key decisions

| Decision | Choice | Why |
|---|---|---|
| DB driver | `mysql-connector-python` (pure-Python mode) | Official, no compiler needed on Windows, works with XAMPP's MariaDB. |
| ORM / Alembic | **Not used** | Plain SQL in repositories is easier to read and debug for this team; financial queries stay explicit. |
| Migrations | Own runner: `migrations/versions/NNNN_name.sql`, tracked in `schema_migrations` with SHA-256 checksum | Versioned, idempotent, never destructive; no extra tool to learn. |
| Money | `Decimal` everywhere, `DECIMAL(12,2)` in MySQL, floats rejected (`utils/money.py`) | Exact centavos. Rounding: ROUND_HALF_UP to 0.01. |
| Quantities | `DECIMAL(12,3)` (allows weighed items) | |
| Inventory costing | **Weighted average cost** (moving average, recalculated on each receipt) | Simple, standard for convenience retail, consistent COGS = qty × avg cost at time of sale (stored on the sale line). |
| SQL mode | Per-session `STRICT_ALL_TABLES`, `NO_ZERO_DATE`, … | Bad data is rejected instead of silently truncated. |
| Isolation | READ COMMITTED; stock rows locked with `SELECT … FOR UPDATE` during sales | Prevents overselling / lost updates. |
| Time zone | Session `+08:00` (Philippines) | Report day boundaries match store hours. |
| Reconnect | Read queries retried once after a lost connection; writes never auto-retried | Avoids duplicate sales. Duplicate submission is also guarded by a unique client token per sale (Phase 5). |
| Passwords (users) | bcrypt (Phase 3) | |
| Secrets in logs | `RedactSecretsFilter` masks `password=`, `pwd:` etc. and the literal DB password | |
| Packaging | PyInstaller one-folder build; `.env`, `logs/`, `backups/` live next to the `.exe` (`config.settings.app_root`) | |

## Error handling
Driver errors are converted to `DatabaseError(user_message, detail)` in
`database/connection.py::friendly_error`. The UI shows `user_message`
(plain language); `detail` goes to `logs/pos.log`. Unexpected exceptions are
caught by a global hook in `main.py`, logged, and shown as a short message.

## Application flow (`ui/app_controller.py`)
1. System check (database reachable, no pending updates) → otherwise `StartupWindow` with fix-it text and *Check again*.
2. No users in the database → `FirstAdminDialog` creates the administrator and logs them in.
3. Otherwise `LoginWindow`. A user with a temporary password must change it (`ChangePasswordDialog`, forced).
4. `MainWindow`: sidebar menu built from the `nav` list in `ui/windows/main_window.py`; an entry is
   added only if `session.can(permission)`. To add a module: create a `Page` subclass in `ui/pages/`
   and one line in `nav`.
5. Log out (Ctrl+L) returns to the login screen. Closing the window also records a logout.

## Permissions
`models.user.Session` holds the logged-in user's permission codes. **Every service method checks
`session.require(...)`** — hiding a menu item is not the security boundary. Actions that need a
second person (discount, void, refund) call `AuthService.approve(username, password, permission, …)`
and record both people.

## Services container
`services/container.py::Services.build(db)` creates each service once; windows receive it.
Repositories take an optional `cur` so a service can write several tables in one transaction,
including its audit entry (`AuditService.record(cur, …)`): the change and its audit record are
saved together or not at all.

## Shifts and the cash drawer (Phase 9)
- `services/shift_service.py`: a cashier must open a shift (count the starting cash) before selling
  (setting `require_shift`); `complete_sale` links the sale to the open shift, locking the shift row
  first, then products (same lock order everywhere: shift → products by id).
- Expected cash = opening cash + cash sales + cash in − cash out − drawer expenses − deliveries paid
  from the drawer + voided drawer expenses put back (`drawer_cash()`).
- Closing is a **blind count**: the cashier types the cash counted (denomination counter); expected and
  over/short are shown only afterwards, and stored on the shift. Managers can close someone else's shift.
- Cash in/out and drawer expenses need manager approval for cashiers; each is idempotent by
  `client_token`. Paying a delivery from the drawer (Receive stock) cannot take more than is in it.

## Reports (Phase 10)
- Owner's scope: dashboard + one daily summary, Excel export (no other reports unless asked).
- `services/report_service.py` reads only; numbers come straight from `sales`, `sale_payments`,
  `expenses` (voided excluded), `shifts` and `stock_receipts`, so they always agree with Sales history.
  Net sales = Σ`sales.total`; gross profit = net sales − Σ`sales.cost_total` (cost at time of sale);
  net profit = gross profit − expenses of the day. A day = 00:00–24:00 local time (+08:00).
- `summary_lines()` gives one list of lines used by both the screen and `reports/excel.py`
  (openpyxl; amounts written as Decimal with a money format, never float).

## Backups (Phase 11)
- `services/backup_service.py` runs XAMPP's `mysqldump` / `mysql` (`POS_MYSQL_BIN_DIR`, else
  `C:\xampp\mysql\bin`, else PATH). The password goes in a temporary option file
  (`--defaults-extra-file`), never on the command line; the file is deleted at once.
- Dump: `--single-transaction --routines --triggers`, no `CREATE DATABASE` (restorable into any DB name),
  gzip, written as `.part` and renamed only after mysqldump exited 0 and the dump ends correctly.
- Daily automatic backup in `AppController._after_database_ok` (failure never blocks the POS; shown in
  Store settings). Keeps the newest 30 `auto` files; `manual`/`before-restore` are never deleted.
- Restore only from `scripts/restore_backup.py` / POS Tools (never from the POS screens), always after a
  `before-restore` backup.

## Packaging (Phase 12)
- `pos.spec`: two programs in one folder sharing `_internal` — `ConvenienceStorePOS.exe` (windowed, `main.py`)
  and `POS Tools.exe` (console, `pos_tools.py` → `scripts/*`). Migrations `.sql` and icons are bundled;
  `.env`, `logs\`, `backups\` live next to the `.exe` (`config.settings.app_root`).
- Files both programs need are collected once (a second copy of a read-only DLL fails).
- Antivirus software on the development PC removed and blocked new scripts and the build; the project
  folder must be an antivirus exception and the PC restarted.

## Checkout design
- `models/cart.py` — the sale in progress, pure Python (no database). Discounts are stored as rules
  (percent/amount + reason + approver) and re-applied whenever quantities change, so they can never
  exceed what they apply to. `sale_discount_shares()` spreads a whole-sale discount over lines by the
  largest-remainder method (exact to the cent).
- `services/sale_service.py::complete_sale` — one transaction: token check (idempotent), discount
  approvals re-verified against the database, product rows locked in id order (no deadlocks), number
  from `doc_sequences`, header/lines/payments inserted, stock deducted with ledger rows, audit entry.
  A unique-key clash on `client_token` (two submits at the same instant) returns the first sale.
- Payments: `apply_payments()` takes non-cash first (must not exceed what is due), cash last (may exceed:
  the excess is change). Total must be covered exactly.
- COGS uses `products.cost_price` at the moment of sale (becomes weighted-average cost in Phase 7).
- `ui/pages/pos_page.py` keeps keyboard focus in the scan box; the cart table never takes focus.
  Approvals go through `ui/dialogs/pos_dialogs.py::authorize()` → `AuthService.approve()`.

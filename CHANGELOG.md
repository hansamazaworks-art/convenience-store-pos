# Changelog

## 1.0.0 — 2026-10-11 — Phases 11–12: backups, Windows program, manual
### Added
- **Automatic daily backup** when the POS starts (one per day, newest 30 kept) with XAMPP's
  `mysqldump`, saved in `backups\` as `.sql.gz`. Half-written backups are never kept.
- **Store settings → Backups**: last backup time, **Back up now**, **Open backups folder**, and a
  warning if the automatic backup failed.
- `scripts\restore_backup.py` (`--list`, `--backup`, `--restore`): restore saves your current data first
  ("before-restore" backup) and asks you to type RESTORE.
- **Windows programs** (`build_exe.bat` → `dist\ConvenienceStorePOS`): `ConvenienceStorePOS.exe` (the POS, no Python
  needed) and `POS Tools.exe` (menu: check computer, create database account, create/update database,
  status, backup, list, restore).
- `MANUAL.md`: installing on the store PC and the daily routine.
### Changed
- `scripts\check_environment.py` and `scripts\create_app_user.py` work from the packaged program
  (they use the program's folder for `.env` and the report).
- Removed the unused old copy of version 0.1 (`convenience_store_pos\convenience_store_pos`).
### Tested
- Backup → change data → restore → data and protective triggers back; restore undone with the
  before-restore backup (on a throw-away test database). Real database backed up before updating it.
- Packaged `POS Tools.exe` showed the real database status (8 updates applied) and listed backups;
  packaged `ConvenienceStorePOS.exe` started, connected and made its daily backup.

## 0.9.0 — 2026-10-11 — Phase 10: dashboard and daily report
### Added
- **Dashboard → Today**: sales and gross profit today (managers/owner), "My sales today" and "My shift"
  (cashiers), number of low-stock items, open shifts and who has them. Each person sees only what their
  role allows.
- **Daily report** screen (owner and managers): pick a day (or Previous/Next day) to see sales,
  discounts, payments per method, cost of items sold, gross profit, expenses per kind, net profit, cash
  sales and each shift's over/short, and the stock bought that day.
- **Save to Excel…**: saves the daily report as an .xlsx file (amounts are real numbers you can add up).
- Cost and profit lines are hidden from roles that may not see cost.
- New package: `openpyxl` (for the Excel files).

## 0.8.0 — 2026-10-11 — Phase 9: shifts, cash drawer, expenses
### Added
- Migration 0008: `shifts`, `expense_categories` (Ice, Delivery, Electricity, Rent, Wages…), `expenses`,
  `cash_movements`; sales now point to the shift they were made in.
- **My shift** screen: open the shift by counting the starting cash, **Cash in** (more change),
  **Cash out** (e.g. to the safe), **Expense from drawer**, **Close shift**.
- Closing is a blind count: type how many of each bill and coin; only then the POS shows the expected
  cash and whether the drawer is OVER, SHORT or exact. Shift report on screen and on the receipt printer.
- **Shifts** screen (managers): all shifts for a period, open any shift's report, close a shift someone
  forgot to close.
- **Expenses** screen (managers): expenses paid from the drawer or from other money, add new kinds,
  void with a reason (never deleted).
- Receive stock: "Paid with cash from my drawer" takes the delivery's cost out of the open shift's cash.
- Cashiers need a manager's approval for cash in/out and drawer expenses.
### Changed
- **The checkout requires an open shift** (owner's choice). The cashier sees a banner and an
  "Open shift" button until the starting cash is counted.
- Refunds/returns are not part of the system (owner's choice).
### Fixed
- Two screen tests updated for the new "My shift" menu item and the shift report label.

## 0.7.0 — 2026-10-11 — Phase 8: suppliers and receiving
### Added
- Migration 0007: `suppliers`, `stock_receipts`, `stock_receipt_lines`.
- **Receive stock** screen ("I buy, then I record"): optional supplier and invoice/DR number, scan or
  search items (scanning again adds one), type quantity and either the cost each or the total paid for
  the line (the other is calculated), warning when cost is above the selling price, **Past deliveries…**.
- Saving a delivery adds the stock and recalculates each product's **weighted-average cost**
  (saved in price history as "Received RC…"). Saved once even if clicked twice; nothing is saved if any
  line is wrong.
- **Suppliers** screen: name, phone, note, number of deliveries, last delivery; turn off/on.

## 0.6.0 — 2026-10-11 — Phase 7: inventory
### Added
- Migration 0006: `stock_adjustments`, `stock_counts`, `stock_count_lines`.
- **Inventory** screen: stock on hand with search, category filter, "Low stock only" (at or below the
  reorder level, shown orange; below zero shown red), stock value at cost (only for roles that may see
  cost), **Movements…** (every stock change for a product, newest first) and **Adjust stock…**.
- Stock adjustments with a reason: damaged, expired, lost, store/family use (remove), found (add),
  correction (either way, note required). Saved once even if the button is clicked twice; audit logged.
- **Stock count** screen: count sheet for all products or one category, scan a barcode to jump to the
  item, save and continue later, finish to set stock to the counted numbers (difference taken at the
  moment of finishing, so sales made during the count are not lost). Also used to enter opening stock.
- Weighted-average cost formula (`services/inventory_service.weighted_average_cost`), used by receiving.
- Store settings → Stock: "Allow selling items the system shows as out of stock".
### Changed
- **The checkout now refuses to sell more than is in stock** (owner's choice). The cashier sees the
  message when scanning, not only at payment. Enter opening stock first (Stock count).
- Expiry dates are not tracked (owner's choice): the "has expiry dates" box was removed from the product form.
- Tests can use a test-only MySQL account (`scripts\create_test_user.py` → `.env.test`).

## 0.5.1 — 2026-10-11 — tests run on Windows
### Fixed
- Tests on Windows: Qt's off-screen mode drew every character as a box because it could not find the Windows fonts; `tests/conftest.py` now points it at `C:\Windows\Fonts`. The app itself was not affected (real receipts print text correctly).
- The receipt PDF test now reads the PDF with Qt's own PDF reader instead of the Linux tools `pdftotext`/`pdfinfo`.

## 0.5.0 — 2026-10-10 — Phase 6: receipts and printing
### Added
- Migration 0005: `sales.receipt_prints` counter; settings `receipt_printer`, `receipt_width_mm` (58/80), `receipt_auto_print`, `receipt_note`.
- Receipt builder (`services/receipt_service.py`): 32 characters per line on 58 mm paper, 42 on 80 mm; store header, sale number/date/cashier, items (long names wrap), item and sale discounts with reasons, bold TOTAL, payments with reference numbers, bold change, item count, note and footer.
- Printing through the Windows printer driver (`ui/printing.py`): any thermal or normal printer; one continuous receipt-length page; font size fitted to the paper width; also Save as PDF.
- Automatic receipt printing after each sale (can be switched off); "Print receipt / Print another copy (P)" on the sale-complete screen.
- The first print is the original; every later print is marked `*** REPRINT ***` and written to the audit log.
- Receipt preview dialog (Print, Save as PDF); "Receipt…" in Sales history → sale detail.
- Store settings → Receipt printer: choose from installed printers, paper width, auto-print, receipt note, Preview/Print test receipt (with a character ruler to check the width).
- A printer problem (off, no paper, not found) shows a clear message and never affects the saved sale.
- 8 new tests (105 total), including PDF output checked for size (58 mm) and content.

## 0.4.0 — 2026-10-10 — Phase 5: checkout
### Added
- Migration 0004: `payment_methods` (Cash, GCash, Maya, Card), `doc_sequences`, `sales`, `sale_lines`, `sale_payments`, `held_sales`, `product_stock`, `stock_movements`; triggers block deleting/changing completed sales, lines, payments and stock movements; setting `allow_negative_stock` = 1.
- Checkout screen (keyboard-first): scan or type + Enter, `3*code` quantity prefix, picker when several products match, ↑/↓ select, +/− quantity, F4 quantity, Del remove, F6 item discount, F7 sale discount, F8 hold, F9 recall, F10 cancel, F12/Space pay.
- Payment: methods as buttons (F1…), quick cash buttons, exact amount, live change, reference number for non-cash, split payments (non-cash first, cash last gives change).
- Sale complete screen with large change amount.
- Manager approval pop-up: cashiers need a manager's login to discount, remove/reduce items or cancel a sale; removals/cancellations are written to the audit log with the approver.
- Sale completion in one transaction: daily gap-free numbers (YYMMDD-NNNN), lines with cost at time of sale (COGS), payments, stock deduction + movement ledger, audit entry. Same cart submitted twice (double Enter, double click, simultaneous) = one sale.
- Whole-sale discounts are split across lines to the cent (stored per line for refunds and product profit).
- Sales history page (managers/admins: all sales; cashiers: their own) with sale detail.
- Payment methods section in Store settings (add, rename, reference required, turn on/off; Cash cannot be turned off).
- Logging out or closing the POS is blocked while a sale is in progress.
- 26 new tests (97 total), including 4 simultaneous submits → 1 sale and a mid-sale failure leaving no trace.
### Fixed
- If the first-time setup window was closed, the program kept running invisibly. The start-up flow now runs inside the Qt event loop.
- Database connection pool now waits briefly when all connections are busy instead of failing.

## 0.3.0 — 2026-10-10 — Phase 4: products and catalog
### Added
- Migration 0003: `categories`, `brands`, `units`, `products`, `product_price_history`; seeded 9 units and 14 categories.
- Products page: live search by name/brand/SKU/barcode (every word must match), category filter, show inactive, F3 focuses search.
- Barcode scanning in the search box: exact barcode/SKU match is selected; an unknown code offers "Add a new product with this barcode".
- Product form: name, barcode, SKU (automatic P000001… if empty), category, brand (add new ones from the form), unit, cost and selling price with live profit/margin, reorder level, expiry tracking flag.
- Price rules: selling price > 0, no negative cost, warning + confirmation when selling below cost; duplicate barcode/SKU rejected (case-insensitive) with the name of the product that has it.
- Every price change saved in price history (viewable per product) and every product change in the audit log.
- Deactivate/activate products (never deleted).
- Categories & brands page with tabs for categories, brands and units (add, rename, activate/deactivate, product counts).
- Cashiers see prices but not cost or margin; only Administrator, Manager and Inventory Staff can change products.
- `Start POS.bat` double-click launcher.
- 19 new tests (71 total).

## 0.2.0 — 2026-10-10 — Phases 2 + 3
### Added
- Migration 0002: `roles`, `permissions`, `role_permissions`, `users`, `audit_log` (append-only via triggers). 5 roles, 26 permission codes covering every planned module.
- Login with bcrypt passwords; 5 wrong passwords lock the account for 5 minutes; same message for unknown user and wrong password.
- First-time setup: if no users exist, the POS asks to create the administrator account.
- Temporary passwords: new users and password resets must choose their own password at first login.
- Main window with left menu (only modules the role may use), top bar (name, role, change password, log out; Ctrl+L), Ctrl+1..9 page shortcuts.
- Pages: Dashboard, Users (add/edit/reset password/enable/disable), Store settings (name, address, phone, tax ID, currency, receipt footer), Audit log (search + date range).
- Safety rules: cannot disable yourself; the last active administrator cannot be disabled or demoted.
- Manager approval helper (`AuthService.approve`) for discounts/voids/refunds in later phases.
- Service-layer permission checks (`Session.require`), friendly error dialogs, `Services` container, `AppController` window flow.
- 22 new tests (service + off-screen UI): 52 total.
### Changed
- Store name and currency now come from the database (Store settings page); `.env` values are only the first-run defaults.
- Fusion style + shared style sheet; dropdown arrow icon in `resources/icons`.

## 0.1.2 — 2026-10-10
### Fixed
- `reset_xampp_root_password.bat` could leave its recovery-mode MySQL running (hung, blocking logins). It now uses connect/shutdown timeouts, force-stops the recovery server if needed, verifies it is gone, and warns not to close the window early.

## 0.1.1 — 2026-10-09
### Fixed
- MySQL login timed out on XAMPP ("_ssl.c handshake operation timed out"): encryption is now off for local connections (`POS_DB_SSL=off`, default), applied in the app, `check_environment.py` and `create_app_user.py`.
- `check_environment.py` blamed the password for every login failure; it now tells wrong password (1045), host not allowed (1130) and connection problems apart.
### Added
- `scripts/reset_xampp_root_password.bat`: double-click reset of the XAMPP root password (recovery mode, hidden password entry, no data touched). Tested end to end against MariaDB 10.11 with PowerShell 7; syntax-checked for Windows PowerShell.
- `check_environment.py` shows the MySQL server version before logging in.

## 0.1.0 — 2026-10-09 — Phase 0 + Phase 1
### Added
- `scripts/check_environment.py`: read-only check of Python, packages, XAMPP, MySQL, existing databases.
- Project structure (config, database, models, repositories, services, ui, reports, migrations, tests, scripts).
- `.env` settings loader with validation; password never printed.
- Database layer: connection pool, strict SQL mode, all-or-nothing transactions, one-time reconnect for reads, plain-language error messages.
- Versioned migration runner + migration 0001 (`app_settings`).
- `scripts/setup_database.py` (create DB if missing, apply updates, refuses to touch a non-POS database).
- `scripts/create_app_user.py` (restricted `pos_app` MySQL account, writes `.env`).
- Rotating log file `logs/pos.log` with password redaction.
- Decimal money helpers (ROUND_HALF_UP, float rejection, change calculation).
- Temporary start-up window showing database status.
- 29 automated tests (21 unit, 8 against a real MariaDB server).

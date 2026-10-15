# Database Schema

Database: `convenience_store_pos` by default; the dev PC uses `convenience_store_pos` (set by `POS_DB_NAME` in `.env`)
Charset: `utf8mb4` / `utf8mb4_unicode_ci`, engine InnoDB.
Apply/update with `scripts\setup_database.py`.

## Applied migrations
| # | File | Contents |
|---|---|---|
| 0001 | `0001_app_settings.sql` | `app_settings` |
| 0002 | `0002_users_roles_permissions.sql` | `roles`, `permissions`, `role_permissions`, `users`, `audit_log` + triggers + seed |
| 0003 | `0003_products_catalog.sql` | `categories`, `brands`, `units`, `products`, `product_price_history` + seed units/categories |
| 0004 | `0004_sales_checkout.sql` | `payment_methods`, `doc_sequences`, `sales`, `sale_lines`, `sale_payments`, `held_sales`, `product_stock`, `stock_movements` + protective triggers |
| 0005 | `0005_receipts.sql` | `sales.receipt_prints`; receipt settings |
| 0006 | `0006_inventory.sql` | `stock_adjustments` (append-only), `stock_counts`, `stock_count_lines`; `allow_negative_stock` set to 0 |
| 0007 | `0007_purchasing.sql` | `suppliers`, `stock_receipts`, `stock_receipt_lines` (+ protective triggers) |
| 0008 | `0008_shifts_cash_expenses.sql` | `shifts`, `expense_categories` (+ seed), `expenses`, `cash_movements` (+ protective triggers); FK `sales.shift_id`; setting `require_shift` = 1 |

## Tables

### schema_migrations (managed by `database/migrator.py`)
| Column | Type | Notes |
|---|---|---|
| version | INT UNSIGNED PK | migration number |
| name | VARCHAR(150) | |
| checksum | CHAR(64) | SHA-256 of the file; warns if edited after applying |
| applied_at | DATETIME | |

### app_settings
| Column | Type | Notes |
|---|---|---|
| setting_key | VARCHAR(100) PK | |
| setting_value | VARCHAR(1000) | |
| updated_at | DATETIME | auto |

Seed keys: `store_name`, `currency_symbol`, `receipt_footer`,
`inventory_costing_method` = `WEIGHTED_AVERAGE`, `allow_negative_stock` (1), `receipt_printer`,
`receipt_width_mm` (58/80), `receipt_auto_print` (1/0), `receipt_note`, plus `store_address`, `store_phone`, `tax_id`.

### roles
`id` SMALLINT PK, `code` (unique: admin, manager, cashier, inventory, purchasing), `name`, `description`, `sort_order`.

### permissions
`code` VARCHAR(50) PK (e.g. `pos.sell`), `module`, `description`. Seeded codes:
dashboard.view, users.manage, settings.manage, audit.view, pos.sell, pos.discount,
pos.void_line, pos.void_sale, pos.refund, pos.reprint, pos.history, products.view,
products.manage, inventory.view, inventory.adjust, inventory.count, suppliers.manage,
purchasing.view, purchasing.manage, purchasing.receive, shifts.own, shifts.manage,
cash.movements, expenses.manage, reports.sales, reports.financial.

### role_permissions
(`role_id`, `permission_code`) PK, FKs cascade. Seed: admin = all; manager = all except
users.manage and settings.manage; cashier = dashboard.view, pos.sell, pos.reprint,
products.view, shifts.own; inventory = dashboard, products.view/manage, inventory.view/adjust/count,
purchasing.receive; purchasing = dashboard, products.view, inventory.view, suppliers.manage,
purchasing.view/manage/receive.

### users
| Column | Type | Notes |
|---|---|---|
| id | INT UNSIGNED PK | |
| username | VARCHAR(50) UNIQUE | case-insensitive (collation), CHECK length ≥ 3 |
| full_name | VARCHAR(100) | |
| password_hash | VARCHAR(255) | bcrypt, cost 12 |
| role_id | FK roles | |
| is_active | TINYINT(1) | disabled users cannot log in; never deleted |
| must_change_password | TINYINT(1) | set for new users and resets |
| failed_attempts, locked_until | | 5 failures → locked 5 minutes |
| last_login_at, password_changed_at, created_at, created_by (FK users), updated_at | | |

### audit_log (append-only)
`id` BIGINT PK, `created_at` DATETIME(3), `user_id` (FK users, NULL for unknown-user login attempts),
`username`, `action` (e.g. `auth.login`, `user.created`, `settings.updated`), `entity_type`,
`entity_id`, `details` (JSON text), `workstation`. Indexed by time, user, action.
Triggers `trg_audit_log_no_update` / `trg_audit_log_no_delete` reject UPDATE and DELETE.

### categories / brands
`id` INT PK, `name` VARCHAR(80) UNIQUE (case-insensitive), `is_active`, timestamps.

### units
`id` SMALLINT PK, `code` VARCHAR(10) UNIQUE (pc, pack, box, bottle, can, sachet, kg, g, L),
`name` UNIQUE, `allow_decimal` (1 = can sell fractions, e.g. kg), `is_active`.

### products
| Column | Type | Notes |
|---|---|---|
| id | INT UNSIGNED PK | |
| sku | VARCHAR(40) UNIQUE | auto `P000001` if not given |
| barcode | VARCHAR(50) UNIQUE NULL | one barcode per product |
| name | VARCHAR(150) | indexed |
| category_id, brand_id | FK, NULL allowed | |
| unit_id | FK units | |
| cost_price | DECIMAL(12,2) ≥ 0 | latest purchase cost; becomes weighted-average cost in Phase 7 |
| selling_price | DECIMAL(12,2) > 0 | shelf price (treated as tax-inclusive) |
| reorder_level | DECIMAL(12,3) ≥ 0 | low-stock threshold (Phase 7) |
| track_expiry | TINYINT(1) | expiry dates captured when receiving (Phase 7) |
| is_active | TINYINT(1) | products are never deleted |
| created_at/by, updated_at/by | | |

### product_price_history
`product_id`, `old/new_cost_price`, `old/new_selling_price`, `changed_at`, `changed_by`, `reason`.
One row on creation and one per edit that changes a price.

### payment_methods
`id`, `code` UNIQUE, `name` UNIQUE, `is_cash` (gives change; only Cash), `requires_reference`, `is_active`, `sort_order`.
Seed: Cash, GCash, Maya, Card.

### doc_sequences
(`seq_key`, `period`) PK, `last_value`. Sale numbers: key `sale`, period `YYMMDD` → `261010-0001`.
Taken inside the sale transaction, so a failed sale does not use up a number.

### sales (header) — never deleted
`sale_no` UNIQUE, `client_token` UNIQUE (the cart's id: a repeated submit returns the first sale),
`cashier_id`, `shift_id` (NULL until Phase 9), `item_count`, `subtotal`, `line_discount`, `sale_discount`,
`discount_total`, `total`, `amount_paid`, `change_given`, `cost_total` (COGS), `sale_discount_reason`,
`sale_discount_approved_by`, `created_at`, `receipt_prints` (0 = never printed; > 0 → next print says REPRINT).
CHECK: total = subtotal − discount_total; discount_total = line + sale discount; amount_paid − change = total.

### sale_lines — never changed or deleted
Copies of `sku`, `barcode`, `name`, `unit_code` (receipts never change), `quantity`, `unit_price`,
`gross_amount`, `line_discount`, `sale_discount_share` (this line's part of the whole-sale discount,
allocated to the cent), `net_amount` = gross − both discounts, `unit_cost` and `cost_amount` (cost at
time of sale), `discount_reason`, `discount_approved_by`.

### sale_payments — never changed or deleted
`payment_method_id`, `amount` (applied), `tendered` (handed over), `change_given`, `reference`.
CHECK tendered − change = amount.

### held_sales
Carts parked at the counter: `label`, `held_by`, `item_count`, `total`, `cart_json`. Deleted when recalled
(they are not sales).

### product_stock
`product_id` PK, `quantity` DECIMAL(14,3) (may be negative while `allow_negative_stock` = 1).

### stock_movements — append-only (triggers)
`product_id`, `movement_type` (sale now; refund, receive, adjust, count, damage, expire, opening later),
`quantity` (+ in / − out), `unit_cost`, `balance_after`, `reference_type`/`reference_id` (e.g. sale id),
`note`, `created_at`, `created_by`.

### stock_adjustments — append-only (triggers) — 0006
One row per manual stock change: `client_token` (UNIQUE, double-click guard), `product_id`, `quantity`
(+/−), `reason` (damaged, expired, lost, own_use, found, correction), `note`, `unit_cost` at the time,
`created_by`, `created_at`. Each row has one `stock_movements` row (`reference_type` = 'adjustment').

### stock_counts / stock_count_lines — 0006
Physical counts (also used for opening stock). Header: `count_no` (`SCyymmdd-NN`), `status`
(draft → posted | cancelled), `note`, `category_id` (NULL = all), created/posted by/at.
Lines: one per product, `counted_qty` (NULL = not counted, skipped), and when posted `system_qty`,
`difference` (= counted − system at posting time) and `unit_cost`. Posting writes `count` movements.
### suppliers — 0007
`name` (UNIQUE), `phone`, `note`, `is_active`, created at/by. Optional on deliveries.

### stock_receipts (header, never deleted) / stock_receipt_lines (never changed) — 0007
A delivery the owner bought ("buy then record"; no purchase orders, no supplier credit).
Header: `receipt_no` (`RCyymmdd-NN`), `client_token` UNIQUE (double-save guard), `supplier_id` (NULL),
`reference` (supplier invoice / DR no.), `note`, `item_count`, `total` paid, `received_by`, `received_at`.
Lines: `product_id`, `quantity`, `unit_cost`, `line_total` (amount paid as typed), `old_cost` and
`new_cost` (product average cost before/after). Each line has one `receive` stock movement.

### shifts — 0008
One cashier's turn at the drawer. `shift_no`, `user_id`, `open_user_id` (= user_id while open, NULL when
closed → UNIQUE gives one open shift per user), `status` open/closed, `opening_float`, `opened_at`,
`closed_at`/`closed_by`, `expected_cash`, `counted_cash`, `difference` (counted − expected; + over,
− short), `close_note`. `sales.shift_id` points here.

### expense_categories / expenses — 0008
Expenses are never deleted (trigger); a manager voids one (`status` = void, `void_reason`, `voided_by`).
`client_token` UNIQUE (double-save guard), `category_id`, `description`, `amount` > 0,
`paid_from` drawer/other (drawer requires `shift_id`), `expense_date`, `created_by`, `approved_by`.

### cash_movements — append-only (triggers) — 0008
Cash into or out of a shift's drawer besides sales. `kind`: cash_in, cash_out, expense, purchase
(delivery paid from the drawer), expense_void (voided drawer expense put back). `amount` always > 0;
the kind gives the direction. `reason`, `reference_type`/`reference_id`, `created_by`, `approved_by`.

Conventions: `id BIGINT UNSIGNED AUTO_INCREMENT` PKs, money `DECIMAL(12,2)`,
quantities `DECIMAL(12,3)`, `created_at`/`created_by` on business rows,
foreign keys `ON DELETE RESTRICT` (completed records are never deleted).

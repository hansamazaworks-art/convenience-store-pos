-- 0004: Checkout - payment methods, sales, sale lines, payments, held sales,
-- document numbering, and the stock ledger that sales deduct from.

CREATE TABLE payment_methods (
    id                 SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    code               VARCHAR(20)  NOT NULL,
    name               VARCHAR(40)  NOT NULL,
    is_cash            TINYINT(1)   NOT NULL DEFAULT 0,  -- cash gives change and goes in the drawer
    requires_reference TINYINT(1)   NOT NULL DEFAULT 0,  -- e.g. GCash reference number
    is_active          TINYINT(1)   NOT NULL DEFAULT 1,
    sort_order         SMALLINT     NOT NULL DEFAULT 0,
    UNIQUE KEY uq_pm_code (code),
    UNIQUE KEY uq_pm_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO payment_methods (code, name, is_cash, requires_reference, sort_order) VALUES
    ('CASH',  'Cash',  1, 0, 1),
    ('GCASH', 'GCash', 0, 1, 2),
    ('MAYA',  'Maya',  0, 1, 3),
    ('CARD',  'Card',  0, 1, 4);

-- Gap-free daily numbering (sales today: 261010-0001, 261010-0002, ...).
CREATE TABLE doc_sequences (
    seq_key    VARCHAR(20)  NOT NULL,
    period     CHAR(8)      NOT NULL,
    last_value INT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (seq_key, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE sales (
    id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    sale_no          VARCHAR(20)   NOT NULL,
    client_token     CHAR(36)      NOT NULL,  -- same token twice = same sale (double-click guard)
    status           ENUM('completed') NOT NULL DEFAULT 'completed',
    cashier_id       INT UNSIGNED  NOT NULL,
    shift_id         BIGINT UNSIGNED NULL,     -- cashier shifts arrive in a later update
    item_count       DECIMAL(12,3) NOT NULL,
    subtotal         DECIMAL(12,2) NOT NULL,   -- before any discount
    line_discount    DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    sale_discount    DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    discount_total   DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    total            DECIMAL(12,2) NOT NULL,   -- what the customer pays
    amount_paid      DECIMAL(12,2) NOT NULL,   -- tendered, all methods
    change_given     DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    cost_total       DECIMAL(12,2) NOT NULL,   -- cost of goods sold at time of sale
    sale_discount_reason VARCHAR(100) NULL,
    sale_discount_approved_by INT UNSIGNED NULL,
    created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_sales_no (sale_no),
    UNIQUE KEY uq_sales_token (client_token),
    KEY ix_sales_created (created_at),
    KEY ix_sales_cashier (cashier_id, created_at),
    CONSTRAINT fk_sales_cashier  FOREIGN KEY (cashier_id) REFERENCES users (id),
    CONSTRAINT fk_sales_disc_by  FOREIGN KEY (sale_discount_approved_by) REFERENCES users (id),
    CONSTRAINT ck_sales_amounts  CHECK (subtotal >= 0 AND total >= 0 AND discount_total >= 0
                                        AND total = subtotal - discount_total
                                        AND discount_total = line_discount + sale_discount
                                        AND amount_paid - change_given = total
                                        AND change_given >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE sale_lines (
    id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    sale_id            BIGINT UNSIGNED NOT NULL,
    line_no            SMALLINT UNSIGNED NOT NULL,
    product_id         INT UNSIGNED  NOT NULL,
    sku                VARCHAR(40)   NOT NULL,   -- copies: the receipt never changes later
    barcode            VARCHAR(50)   NULL,
    name               VARCHAR(150)  NOT NULL,
    unit_code          VARCHAR(10)   NOT NULL,
    quantity           DECIMAL(12,3) NOT NULL,
    unit_price         DECIMAL(12,2) NOT NULL,
    gross_amount       DECIMAL(12,2) NOT NULL,   -- quantity x unit price
    line_discount      DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    sale_discount_share DECIMAL(12,2) NOT NULL DEFAULT 0.00,  -- this line's part of a whole-sale discount
    net_amount         DECIMAL(12,2) NOT NULL,   -- gross - both discounts
    unit_cost          DECIMAL(12,2) NOT NULL,
    cost_amount        DECIMAL(12,2) NOT NULL,
    discount_reason    VARCHAR(100)  NULL,
    discount_approved_by INT UNSIGNED NULL,
    UNIQUE KEY uq_sale_lines (sale_id, line_no),
    KEY ix_sale_lines_product (product_id),
    CONSTRAINT fk_sl_sale    FOREIGN KEY (sale_id) REFERENCES sales (id),
    CONSTRAINT fk_sl_product FOREIGN KEY (product_id) REFERENCES products (id),
    CONSTRAINT fk_sl_disc_by FOREIGN KEY (discount_approved_by) REFERENCES users (id),
    CONSTRAINT ck_sl_amounts CHECK (quantity > 0 AND unit_price >= 0 AND line_discount >= 0
                                    AND sale_discount_share >= 0
                                    AND net_amount = gross_amount - line_discount - sale_discount_share
                                    AND net_amount >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE sale_payments (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    sale_id           BIGINT UNSIGNED NOT NULL,
    payment_method_id SMALLINT UNSIGNED NOT NULL,
    amount            DECIMAL(12,2) NOT NULL,   -- amount applied to the sale
    tendered          DECIMAL(12,2) NOT NULL,   -- amount handed over (cash may be more)
    change_given      DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    reference         VARCHAR(60)   NULL,
    KEY ix_sp_sale (sale_id),
    KEY ix_sp_method (payment_method_id),
    CONSTRAINT fk_sp_sale   FOREIGN KEY (sale_id) REFERENCES sales (id),
    CONSTRAINT fk_sp_method FOREIGN KEY (payment_method_id) REFERENCES payment_methods (id),
    CONSTRAINT ck_sp_amounts CHECK (amount > 0 AND tendered - change_given = amount AND change_given >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Sales put on hold at the counter (customer forgot wallet, etc.).
CREATE TABLE held_sales (
    id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    label      VARCHAR(60)   NOT NULL,
    held_by    INT UNSIGNED  NOT NULL,
    item_count DECIMAL(12,3) NOT NULL,
    total      DECIMAL(12,2) NOT NULL,
    cart_json  MEDIUMTEXT    NOT NULL,
    created_at DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_held_user FOREIGN KEY (held_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------ stock ledger
-- Current quantity per product (can go negative if items are sold before
-- stock is recorded; inventory screens arrive in a later update).
CREATE TABLE product_stock (
    product_id INT UNSIGNED  NOT NULL PRIMARY KEY,
    quantity   DECIMAL(14,3) NOT NULL DEFAULT 0.000,
    updated_at DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_ps_product FOREIGN KEY (product_id) REFERENCES products (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Every change to stock, with the reason. Never edited or deleted.
CREATE TABLE stock_movements (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    product_id     INT UNSIGNED  NOT NULL,
    movement_type  VARCHAR(20)   NOT NULL,   -- sale, refund, receive, adjust, count, damage, expire, opening
    quantity       DECIMAL(14,3) NOT NULL,   -- + in, - out
    unit_cost      DECIMAL(12,2) NOT NULL,
    balance_after  DECIMAL(14,3) NOT NULL,
    reference_type VARCHAR(20)   NULL,
    reference_id   BIGINT UNSIGNED NULL,
    note           VARCHAR(200)  NULL,
    created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by     INT UNSIGNED  NULL,
    KEY ix_sm_product (product_id, created_at),
    KEY ix_sm_reference (reference_type, reference_id),
    CONSTRAINT fk_sm_product FOREIGN KEY (product_id) REFERENCES products (id),
    CONSTRAINT fk_sm_user    FOREIGN KEY (created_by) REFERENCES users (id),
    CONSTRAINT ck_sm_qty     CHECK (quantity <> 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TRIGGER trg_stock_movements_no_update BEFORE UPDATE ON stock_movements
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'stock_movements is append-only';

CREATE TRIGGER trg_stock_movements_no_delete BEFORE DELETE ON stock_movements
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'stock_movements is append-only';

-- Completed sales are never edited or deleted (corrections are refunds).
CREATE TRIGGER trg_sales_no_delete BEFORE DELETE ON sales
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'completed sales cannot be deleted';

CREATE TRIGGER trg_sale_lines_no_update BEFORE UPDATE ON sale_lines
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sale lines cannot be changed';

CREATE TRIGGER trg_sale_lines_no_delete BEFORE DELETE ON sale_lines
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sale lines cannot be deleted';

CREATE TRIGGER trg_sale_payments_no_change BEFORE UPDATE ON sale_payments
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sale payments cannot be changed';

CREATE TRIGGER trg_sale_payments_no_delete BEFORE DELETE ON sale_payments
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sale payments cannot be deleted';

-- 1 = items can be sold even if the system shows no stock (stock goes negative and
-- is corrected when deliveries/counts are recorded).
INSERT INTO app_settings (setting_key, setting_value) VALUES ('allow_negative_stock', '1');

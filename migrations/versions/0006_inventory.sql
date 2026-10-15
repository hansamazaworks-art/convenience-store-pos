-- 0006: Inventory - stock adjustments (damaged, lost, found...) and physical stock counts.
-- Stock balances stay in product_stock; every change is a row in stock_movements.

-- One row per adjustment. client_token makes a double-click save only once.
CREATE TABLE stock_adjustments (
    id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_token CHAR(36)      NOT NULL,
    product_id   INT UNSIGNED  NOT NULL,
    quantity     DECIMAL(14,3) NOT NULL,   -- + found / added, - damaged / lost / used
    reason       VARCHAR(20)   NOT NULL,   -- damaged, expired, lost, own_use, found, correction
    note         VARCHAR(200)  NULL,
    unit_cost    DECIMAL(12,2) NOT NULL,   -- cost at the time (value of the loss)
    created_by   INT UNSIGNED  NOT NULL,
    created_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_sa_token (client_token),
    KEY ix_sa_created (created_at),
    CONSTRAINT fk_sa_product FOREIGN KEY (product_id) REFERENCES products (id),
    CONSTRAINT fk_sa_user    FOREIGN KEY (created_by) REFERENCES users (id),
    CONSTRAINT ck_sa_qty     CHECK (quantity <> 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TRIGGER trg_stock_adjustments_no_update BEFORE UPDATE ON stock_adjustments
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'stock adjustments cannot be changed';

CREATE TRIGGER trg_stock_adjustments_no_delete BEFORE DELETE ON stock_adjustments
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'stock adjustments cannot be deleted';

-- A physical count: started as a draft, numbers typed in, then posted once.
CREATE TABLE stock_counts (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    count_no    VARCHAR(20)   NOT NULL,
    status      ENUM('draft', 'posted', 'cancelled') NOT NULL DEFAULT 'draft',
    note        VARCHAR(200)  NULL,
    category_id INT UNSIGNED  NULL,       -- NULL = all products
    created_by  INT UNSIGNED  NOT NULL,
    created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    posted_by   INT UNSIGNED  NULL,
    posted_at   DATETIME      NULL,
    UNIQUE KEY uq_sc_no (count_no),
    CONSTRAINT fk_sc_category FOREIGN KEY (category_id) REFERENCES categories (id),
    CONSTRAINT fk_sc_created  FOREIGN KEY (created_by) REFERENCES users (id),
    CONSTRAINT fk_sc_posted   FOREIGN KEY (posted_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE stock_count_lines (
    id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    count_id     BIGINT UNSIGNED NOT NULL,
    product_id   INT UNSIGNED  NOT NULL,
    counted_qty  DECIMAL(14,3) NULL,       -- NULL = not counted (skipped when posting)
    system_qty   DECIMAL(14,3) NULL,       -- filled when posted: what the system had
    difference   DECIMAL(14,3) NULL,       -- counted - system, filled when posted
    unit_cost    DECIMAL(12,2) NULL,
    UNIQUE KEY uq_scl (count_id, product_id),
    CONSTRAINT fk_scl_count   FOREIGN KEY (count_id) REFERENCES stock_counts (id),
    CONSTRAINT fk_scl_product FOREIGN KEY (product_id) REFERENCES products (id),
    CONSTRAINT ck_scl_qty     CHECK (counted_qty IS NULL OR counted_qty >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Owner's decision (2026-10-11): the checkout refuses to sell more than is in stock.
-- Enter opening stock (Inventory > Stock count) before selling. Can be switched in Store settings.
UPDATE app_settings SET setting_value = '0' WHERE setting_key = 'allow_negative_stock';

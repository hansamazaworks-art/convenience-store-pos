-- 0007: Suppliers and receiving stock ("I buy, then I record it").
-- No purchase orders and no supplier credit (owner's decision 2026-10-11): a delivery is
-- recorded with what arrived and what was paid; the supplier is optional.

CREATE TABLE suppliers (
    id         INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL,
    phone      VARCHAR(50)  NULL,
    note       VARCHAR(200) NULL,
    is_active  TINYINT(1)   NOT NULL DEFAULT 1,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by INT UNSIGNED NULL,
    UNIQUE KEY uq_suppliers_name (name),
    CONSTRAINT fk_suppliers_created_by FOREIGN KEY (created_by) REFERENCES users (id),
    CONSTRAINT ck_suppliers_name CHECK (CHAR_LENGTH(name) >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- One delivery / purchase. client_token: the same screen saved twice = one receipt.
CREATE TABLE stock_receipts (
    id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    receipt_no   VARCHAR(20)   NOT NULL,
    client_token CHAR(36)      NOT NULL,
    supplier_id  INT UNSIGNED  NULL,
    reference    VARCHAR(60)   NULL,      -- supplier's invoice / delivery receipt number
    note         VARCHAR(200)  NULL,
    item_count   DECIMAL(14,3) NOT NULL,
    total        DECIMAL(12,2) NOT NULL,  -- what was paid for the goods
    received_by  INT UNSIGNED  NOT NULL,
    received_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_sr_no (receipt_no),
    UNIQUE KEY uq_sr_token (client_token),
    KEY ix_sr_received (received_at),
    KEY ix_sr_supplier (supplier_id, received_at),
    CONSTRAINT fk_sr_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_sr_user     FOREIGN KEY (received_by) REFERENCES users (id),
    CONSTRAINT ck_sr_total    CHECK (total >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE stock_receipt_lines (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    receipt_id  BIGINT UNSIGNED NOT NULL,
    line_no     SMALLINT UNSIGNED NOT NULL,
    product_id  INT UNSIGNED  NOT NULL,
    quantity    DECIMAL(14,3) NOT NULL,
    unit_cost   DECIMAL(12,2) NOT NULL,   -- cost per unit of this delivery
    line_total  DECIMAL(12,2) NOT NULL,   -- amount paid for this line
    old_cost    DECIMAL(12,2) NOT NULL,   -- product cost before (average)
    new_cost    DECIMAL(12,2) NOT NULL,   -- product cost after (weighted average)
    UNIQUE KEY uq_srl (receipt_id, line_no),
    KEY ix_srl_product (product_id),
    CONSTRAINT fk_srl_receipt FOREIGN KEY (receipt_id) REFERENCES stock_receipts (id),
    CONSTRAINT fk_srl_product FOREIGN KEY (product_id) REFERENCES products (id),
    CONSTRAINT ck_srl CHECK (quantity > 0 AND unit_cost >= 0 AND line_total >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Recorded deliveries are permanent; mistakes are fixed with a stock adjustment.
CREATE TRIGGER trg_stock_receipts_no_delete BEFORE DELETE ON stock_receipts
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'stock receipts cannot be deleted';

CREATE TRIGGER trg_stock_receipt_lines_no_update BEFORE UPDATE ON stock_receipt_lines
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'stock receipt lines cannot be changed';

CREATE TRIGGER trg_stock_receipt_lines_no_delete BEFORE DELETE ON stock_receipt_lines
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'stock receipt lines cannot be deleted';

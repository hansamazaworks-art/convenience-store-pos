-- 0008: Cashier shifts, cash in/out of the drawer, and expenses.
-- Owner's decisions (2026-10-11): a shift must be open to sell; closing is a blind count
-- (expected cash shown only after the count); small expenses are paid from the drawer.

CREATE TABLE shifts (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    shift_no      VARCHAR(20)   NOT NULL,
    user_id       INT UNSIGNED  NOT NULL,
    open_user_id  INT UNSIGNED  NULL,     -- = user_id while open, NULL when closed (one open shift per user)
    status        ENUM('open', 'closed') NOT NULL DEFAULT 'open',
    opening_float DECIMAL(12,2) NOT NULL,  -- cash in the drawer at the start (change fund)
    opened_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at     DATETIME      NULL,
    closed_by     INT UNSIGNED  NULL,
    expected_cash DECIMAL(12,2) NULL,      -- filled at closing
    counted_cash  DECIMAL(12,2) NULL,
    difference    DECIMAL(12,2) NULL,      -- counted - expected (+ over, - short)
    close_note    VARCHAR(200)  NULL,
    UNIQUE KEY uq_shifts_no (shift_no),
    UNIQUE KEY uq_shifts_open_user (open_user_id),
    KEY ix_shifts_user (user_id, opened_at),
    KEY ix_shifts_opened (opened_at),
    CONSTRAINT fk_shifts_user   FOREIGN KEY (user_id) REFERENCES users (id),
    CONSTRAINT fk_shifts_closer FOREIGN KEY (closed_by) REFERENCES users (id),
    CONSTRAINT ck_shifts_float  CHECK (opening_float >= 0),
    CONSTRAINT ck_shifts_count  CHECK (counted_cash IS NULL OR counted_cash >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE sales ADD CONSTRAINT fk_sales_shift FOREIGN KEY (shift_id) REFERENCES shifts (id);

CREATE TABLE expense_categories (
    id        SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name      VARCHAR(60) NOT NULL,
    is_active TINYINT(1)  NOT NULL DEFAULT 1,
    UNIQUE KEY uq_expcat_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO expense_categories (name) VALUES
    ('Ice'), ('Delivery / transport'), ('Cellphone load'), ('Cleaning supplies'),
    ('Store supplies (bags, tape)'), ('Electricity'), ('Water'), ('Rent'), ('Wages'),
    ('Repairs'), ('Others');

-- Expenses: paid from the drawer (linked to the shift) or from other money.
-- Never deleted; a manager can void one (status 'void') with a reason.
CREATE TABLE expenses (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_token  CHAR(36)      NOT NULL,
    category_id   SMALLINT UNSIGNED NOT NULL,
    description   VARCHAR(200)  NULL,
    amount        DECIMAL(12,2) NOT NULL,
    paid_from     ENUM('drawer', 'other') NOT NULL,
    shift_id      BIGINT UNSIGNED NULL,
    expense_date  DATE          NOT NULL,
    status        ENUM('active', 'void') NOT NULL DEFAULT 'active',
    void_reason   VARCHAR(200)  NULL,
    voided_by     INT UNSIGNED  NULL,
    created_by    INT UNSIGNED  NOT NULL,
    approved_by   INT UNSIGNED  NULL,
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_exp_token (client_token),
    KEY ix_exp_date (expense_date),
    CONSTRAINT fk_exp_cat     FOREIGN KEY (category_id) REFERENCES expense_categories (id),
    CONSTRAINT fk_exp_shift   FOREIGN KEY (shift_id) REFERENCES shifts (id),
    CONSTRAINT fk_exp_user    FOREIGN KEY (created_by) REFERENCES users (id),
    CONSTRAINT fk_exp_approve FOREIGN KEY (approved_by) REFERENCES users (id),
    CONSTRAINT fk_exp_void    FOREIGN KEY (voided_by) REFERENCES users (id),
    CONSTRAINT ck_exp_amount  CHECK (amount > 0),
    CONSTRAINT ck_exp_drawer  CHECK (paid_from = 'other' OR shift_id IS NOT NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TRIGGER trg_expenses_no_delete BEFORE DELETE ON expenses
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'expenses cannot be deleted';

-- Every cash movement in or out of a drawer during a shift (besides sales).
-- kind: cash_in (more change added), cash_out (cash taken out, e.g. to the safe),
--       expense (paid an expense), purchase (paid a delivery), expense_void (voided expense put back)
CREATE TABLE cash_movements (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_token   CHAR(36)      NOT NULL,
    shift_id       BIGINT UNSIGNED NOT NULL,
    kind           VARCHAR(20)   NOT NULL,
    amount         DECIMAL(12,2) NOT NULL,   -- always positive; kind gives the direction
    reason         VARCHAR(200)  NULL,
    reference_type VARCHAR(20)   NULL,
    reference_id   BIGINT UNSIGNED NULL,
    created_by     INT UNSIGNED  NOT NULL,
    approved_by    INT UNSIGNED  NULL,
    created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_cm_token (client_token),
    KEY ix_cm_shift (shift_id),
    CONSTRAINT fk_cm_shift   FOREIGN KEY (shift_id) REFERENCES shifts (id),
    CONSTRAINT fk_cm_user    FOREIGN KEY (created_by) REFERENCES users (id),
    CONSTRAINT fk_cm_approve FOREIGN KEY (approved_by) REFERENCES users (id),
    CONSTRAINT ck_cm_amount  CHECK (amount > 0),
    CONSTRAINT ck_cm_kind    CHECK (kind IN ('cash_in', 'cash_out', 'expense', 'purchase', 'expense_void'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TRIGGER trg_cash_movements_no_update BEFORE UPDATE ON cash_movements
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'cash movements cannot be changed';

CREATE TRIGGER trg_cash_movements_no_delete BEFORE DELETE ON cash_movements
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'cash movements cannot be deleted';

-- 1 = a cashier must open a shift (count the starting cash) before selling.
INSERT INTO app_settings (setting_key, setting_value) VALUES ('require_shift', '1');

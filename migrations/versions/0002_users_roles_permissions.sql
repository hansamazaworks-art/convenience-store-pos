-- 0002: Roles, permissions, users and the audit log.

CREATE TABLE roles (
    id          SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    code        VARCHAR(30)  NOT NULL,
    name        VARCHAR(60)  NOT NULL,
    description VARCHAR(255) NOT NULL DEFAULT '',
    sort_order  SMALLINT     NOT NULL DEFAULT 0,
    UNIQUE KEY uq_roles_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE permissions (
    code        VARCHAR(50)  NOT NULL PRIMARY KEY,
    module      VARCHAR(30)  NOT NULL,
    description VARCHAR(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE role_permissions (
    role_id         SMALLINT UNSIGNED NOT NULL,
    permission_code VARCHAR(50)       NOT NULL,
    PRIMARY KEY (role_id, permission_code),
    CONSTRAINT fk_rp_role FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE CASCADE,
    CONSTRAINT fk_rp_perm FOREIGN KEY (permission_code) REFERENCES permissions (code) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE users (
    id                   INT UNSIGNED      NOT NULL AUTO_INCREMENT PRIMARY KEY,
    username             VARCHAR(50)       NOT NULL,
    full_name            VARCHAR(100)      NOT NULL,
    password_hash        VARCHAR(255)      NOT NULL,
    role_id              SMALLINT UNSIGNED NOT NULL,
    is_active            TINYINT(1)        NOT NULL DEFAULT 1,
    must_change_password TINYINT(1)        NOT NULL DEFAULT 0,
    failed_attempts      SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    locked_until         DATETIME          NULL,
    last_login_at        DATETIME          NULL,
    password_changed_at  DATETIME          NULL,
    created_at           DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by           INT UNSIGNED      NULL,
    updated_at           DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_users_username (username),
    KEY ix_users_role (role_id),
    CONSTRAINT fk_users_role FOREIGN KEY (role_id) REFERENCES roles (id),
    CONSTRAINT fk_users_created_by FOREIGN KEY (created_by) REFERENCES users (id),
    CONSTRAINT ck_users_username_len CHECK (CHAR_LENGTH(username) >= 3),
    CONSTRAINT ck_users_full_name CHECK (CHAR_LENGTH(full_name) >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE audit_log (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    created_at  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    user_id     INT UNSIGNED    NULL,
    username    VARCHAR(50)     NULL,
    action      VARCHAR(60)     NOT NULL,
    entity_type VARCHAR(40)     NULL,
    entity_id   VARCHAR(40)     NULL,
    details     TEXT            NULL,
    workstation VARCHAR(100)    NULL,
    KEY ix_audit_created (created_at),
    KEY ix_audit_user (user_id, created_at),
    KEY ix_audit_action (action, created_at),
    CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- The audit log is append-only: no edits, no deletions.
CREATE TRIGGER trg_audit_log_no_update BEFORE UPDATE ON audit_log
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_log is append-only';

CREATE TRIGGER trg_audit_log_no_delete BEFORE DELETE ON audit_log
    FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_log is append-only';

-- ------------------------------------------------------------------ seed data
INSERT INTO roles (code, name, description, sort_order) VALUES
    ('admin',      'Administrator',   'Full access, including users and settings', 1),
    ('manager',    'Manager',         'Runs the store; approves discounts, voids and refunds', 2),
    ('cashier',    'Cashier',         'Sells at the counter and handles own shift', 3),
    ('inventory',  'Inventory Staff', 'Products, stock counts, adjustments and receiving', 4),
    ('purchasing', 'Purchasing Staff','Suppliers, purchase orders and receiving', 5);

INSERT INTO permissions (code, module, description) VALUES
    ('dashboard.view',      'dashboard',  'See the dashboard'),
    ('users.manage',        'users',      'Create, edit and disable user accounts'),
    ('settings.manage',     'settings',   'Change store settings'),
    ('audit.view',          'audit',      'View the audit log'),
    ('pos.sell',            'pos',        'Ring up sales at the checkout'),
    ('pos.discount',        'pos',        'Give discounts (or approve them for others)'),
    ('pos.void_line',       'pos',        'Remove items from a sale in progress'),
    ('pos.void_sale',       'pos',        'Cancel a whole sale in progress'),
    ('pos.refund',          'pos',        'Process returns and refunds'),
    ('pos.reprint',         'pos',        'Reprint receipts'),
    ('pos.history',         'pos',        'View sales history'),
    ('products.view',       'products',   'View products and prices'),
    ('products.manage',     'products',   'Create and edit products, categories and prices'),
    ('inventory.view',      'inventory',  'View stock levels and movements'),
    ('inventory.adjust',    'inventory',  'Adjust stock, record damaged or expired items'),
    ('inventory.count',     'inventory',  'Perform physical stock counts'),
    ('suppliers.manage',    'purchasing', 'Create and edit suppliers'),
    ('purchasing.view',     'purchasing', 'View purchase orders and supplier invoices'),
    ('purchasing.manage',   'purchasing', 'Create purchase orders, invoices, returns and payments'),
    ('purchasing.receive',  'purchasing', 'Receive deliveries into stock'),
    ('shifts.own',          'cash',       'Open and close own cashier shift'),
    ('shifts.manage',       'cash',       'View and reconcile all shifts'),
    ('cash.movements',      'cash',       'Record cash-in and cash-out'),
    ('expenses.manage',     'expenses',   'Record expenses'),
    ('reports.sales',       'reports',    'View sales reports'),
    ('reports.financial',   'reports',    'View profit, cost and inventory value reports');

-- Administrator: everything
INSERT INTO role_permissions (role_id, permission_code)
SELECT r.id, p.code FROM roles r CROSS JOIN permissions p WHERE r.code = 'admin';

-- Manager: everything except user accounts and store settings
INSERT INTO role_permissions (role_id, permission_code)
SELECT r.id, p.code FROM roles r CROSS JOIN permissions p
WHERE r.code = 'manager' AND p.code NOT IN ('users.manage', 'settings.manage');

INSERT INTO role_permissions (role_id, permission_code)
SELECT r.id, p.code FROM roles r JOIN permissions p
  ON p.code IN ('dashboard.view', 'pos.sell', 'pos.reprint', 'products.view', 'shifts.own')
WHERE r.code = 'cashier';

INSERT INTO role_permissions (role_id, permission_code)
SELECT r.id, p.code FROM roles r JOIN permissions p
  ON p.code IN ('dashboard.view', 'products.view', 'products.manage', 'inventory.view',
                'inventory.adjust', 'inventory.count', 'purchasing.receive')
WHERE r.code = 'inventory';

INSERT INTO role_permissions (role_id, permission_code)
SELECT r.id, p.code FROM roles r JOIN permissions p
  ON p.code IN ('dashboard.view', 'products.view', 'inventory.view', 'suppliers.manage',
                'purchasing.view', 'purchasing.manage', 'purchasing.receive')
WHERE r.code = 'purchasing';

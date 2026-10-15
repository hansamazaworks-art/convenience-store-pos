-- 0001: Store-wide settings (key/value).
-- Business tables (users, roles, products, sales...) arrive in Phase 3+.

CREATE TABLE app_settings (
    setting_key   VARCHAR(100)  NOT NULL PRIMARY KEY,
    setting_value VARCHAR(1000) NOT NULL,
    updated_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO app_settings (setting_key, setting_value) VALUES
    ('store_name', 'My Convenience Store'),
    ('currency_symbol', '₱'),
    ('receipt_footer', 'Thank you for shopping!'),
    ('inventory_costing_method', 'WEIGHTED_AVERAGE');

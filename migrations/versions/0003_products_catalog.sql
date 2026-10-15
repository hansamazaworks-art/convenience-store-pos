-- 0003: Product catalog - categories, brands, units, products, price history.
-- Stock quantities are NOT stored here; they arrive with inventory (Phase 7).

CREATE TABLE categories (
    id         INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(80)  NOT NULL,
    is_active  TINYINT(1)   NOT NULL DEFAULT 1,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_categories_name (name),
    CONSTRAINT ck_categories_name CHECK (CHAR_LENGTH(name) >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE brands (
    id         INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(80)  NOT NULL,
    is_active  TINYINT(1)   NOT NULL DEFAULT 1,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_brands_name (name),
    CONSTRAINT ck_brands_name CHECK (CHAR_LENGTH(name) >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE units (
    id            SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    code          VARCHAR(10) NOT NULL,
    name          VARCHAR(40) NOT NULL,
    allow_decimal TINYINT(1)  NOT NULL DEFAULT 0,  -- 1 = can sell 0.25 kg etc.
    is_active     TINYINT(1)  NOT NULL DEFAULT 1,
    UNIQUE KEY uq_units_code (code),
    UNIQUE KEY uq_units_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE products (
    id             INT UNSIGNED  NOT NULL AUTO_INCREMENT PRIMARY KEY,
    sku            VARCHAR(40)   NOT NULL,
    barcode        VARCHAR(50)   NULL,
    name           VARCHAR(150)  NOT NULL,
    category_id    INT UNSIGNED  NULL,
    brand_id       INT UNSIGNED  NULL,
    unit_id        SMALLINT UNSIGNED NOT NULL,
    cost_price     DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    selling_price  DECIMAL(12,2) NOT NULL,
    reorder_level  DECIMAL(12,3) NOT NULL DEFAULT 0.000,
    track_expiry   TINYINT(1)    NOT NULL DEFAULT 0,
    is_active      TINYINT(1)    NOT NULL DEFAULT 1,
    created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by     INT UNSIGNED  NULL,
    updated_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by     INT UNSIGNED  NULL,
    UNIQUE KEY uq_products_sku (sku),
    UNIQUE KEY uq_products_barcode (barcode),          -- NULLs allowed, duplicates not
    KEY ix_products_name (name),
    KEY ix_products_category (category_id, is_active),
    KEY ix_products_brand (brand_id),
    CONSTRAINT fk_products_category FOREIGN KEY (category_id) REFERENCES categories (id),
    CONSTRAINT fk_products_brand    FOREIGN KEY (brand_id)    REFERENCES brands (id),
    CONSTRAINT fk_products_unit     FOREIGN KEY (unit_id)     REFERENCES units (id),
    CONSTRAINT fk_products_created_by FOREIGN KEY (created_by) REFERENCES users (id),
    CONSTRAINT fk_products_updated_by FOREIGN KEY (updated_by) REFERENCES users (id),
    CONSTRAINT ck_products_cost    CHECK (cost_price >= 0),
    CONSTRAINT ck_products_price   CHECK (selling_price > 0),
    CONSTRAINT ck_products_reorder CHECK (reorder_level >= 0),
    CONSTRAINT ck_products_name    CHECK (CHAR_LENGTH(name) >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Every price change is kept (for reports and audits).
CREATE TABLE product_price_history (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    product_id        INT UNSIGNED  NOT NULL,
    old_cost_price    DECIMAL(12,2) NULL,
    new_cost_price    DECIMAL(12,2) NOT NULL,
    old_selling_price DECIMAL(12,2) NULL,
    new_selling_price DECIMAL(12,2) NOT NULL,
    changed_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changed_by        INT UNSIGNED  NULL,
    reason            VARCHAR(100)  NOT NULL DEFAULT '',
    KEY ix_pph_product (product_id, changed_at),
    CONSTRAINT fk_pph_product FOREIGN KEY (product_id) REFERENCES products (id),
    CONSTRAINT fk_pph_user    FOREIGN KEY (changed_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------------ seed data
INSERT INTO units (code, name, allow_decimal) VALUES
    ('pc',     'Piece',  0),
    ('pack',   'Pack',   0),
    ('box',    'Box',    0),
    ('bottle', 'Bottle', 0),
    ('can',    'Can',    0),
    ('sachet', 'Sachet', 0),
    ('kg',     'Kilogram', 1),
    ('g',      'Gram',   1),
    ('L',      'Liter',  1);

INSERT INTO categories (name) VALUES
    ('Beverages'), ('Snacks'), ('Canned & Packaged Food'), ('Instant Noodles'),
    ('Bread & Pastries'), ('Dairy & Eggs'), ('Frozen'), ('Condiments & Cooking'),
    ('Personal Care'), ('Household & Cleaning'), ('Medicine & First Aid'),
    ('Cigarettes'), ('Load & Bills'), ('Others');

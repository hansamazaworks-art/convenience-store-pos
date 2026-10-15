-- 0005: Receipt printing settings and a print counter per sale (first print vs. reprint).

ALTER TABLE sales ADD COLUMN receipt_prints SMALLINT UNSIGNED NOT NULL DEFAULT 0;

INSERT INTO app_settings (setting_key, setting_value) VALUES
    ('receipt_printer', ''),          -- Windows printer name; empty = not chosen yet
    ('receipt_width_mm', '58'),       -- 58 or 80
    ('receipt_auto_print', '1'),      -- 1 = print automatically after each sale
    ('receipt_note', '');             -- optional extra line(s) at the bottom

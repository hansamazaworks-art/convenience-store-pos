"""SQL for sales, payments, held sales, payment methods and numbering."""
from __future__ import annotations

from datetime import date, timedelta

from repositories.base import Repository


class SaleRepository(Repository):
    # ------------------------------------------------------- numbering
    def next_number(self, cur, seq_key: str, period: str) -> int:
        self._exec(cur, "INSERT IGNORE INTO doc_sequences (seq_key, period, last_value) "
                        "VALUES (%s, %s, 0)", (seq_key, period))
        row = self._one("SELECT last_value FROM doc_sequences WHERE seq_key = %s AND period = %s "
                        "FOR UPDATE", (seq_key, period), cur)
        n = int(row["last_value"]) + 1
        self._exec(cur, "UPDATE doc_sequences SET last_value = %s WHERE seq_key = %s AND period = %s",
                   (n, seq_key, period))
        return n

    def db_now(self, cur) -> dict:
        return self._one("SELECT NOW() AS now, DATE_FORMAT(NOW(), '%y%m%d') AS period", (), cur)

    # ----------------------------------------------------------- sales
    def find_by_token(self, token: str, cur=None) -> dict | None:
        return self._one("SELECT id, sale_no, total, change_given, amount_paid, created_at "
                         "FROM sales WHERE client_token = %s", (token,), cur)

    def insert_sale(self, cur, **v) -> int:
        cols = ["sale_no", "client_token", "cashier_id", "shift_id", "item_count", "subtotal",
                "line_discount", "sale_discount", "discount_total", "total", "amount_paid",
                "change_given", "cost_total", "sale_discount_reason", "sale_discount_approved_by"]
        return self._exec(cur, f"INSERT INTO sales ({', '.join(cols)}) VALUES "
                               f"({', '.join(['%s'] * len(cols))})", [v[c] for c in cols])

    def insert_line(self, cur, **v) -> None:
        cols = ["sale_id", "line_no", "product_id", "sku", "barcode", "name", "unit_code",
                "quantity", "unit_price", "gross_amount", "line_discount", "sale_discount_share",
                "net_amount", "unit_cost", "cost_amount", "discount_reason", "discount_approved_by"]
        self._exec(cur, f"INSERT INTO sale_lines ({', '.join(cols)}) VALUES "
                        f"({', '.join(['%s'] * len(cols))})", [v[c] for c in cols])

    def insert_payment(self, cur, sale_id, method_id, amount, tendered, change, reference) -> None:
        self._exec(cur, "INSERT INTO sale_payments (sale_id, payment_method_id, amount, tendered, "
                        "change_given, reference) VALUES (%s, %s, %s, %s, %s, %s)",
                   (sale_id, method_id, amount, tendered, change, reference))

    def search(self, *, date_from: date, date_to: date, text: str = "",
               cashier_id: int | None = None, limit: int = 1000, cur=None) -> list[dict]:
        where = ["s.created_at >= %s", "s.created_at < %s"]
        params: list = [date_from, date_to + timedelta(days=1)]
        if cashier_id:
            where.append("s.cashier_id = %s")
            params.append(cashier_id)
        if text:
            where.append("(s.sale_no LIKE %s OR EXISTS (SELECT 1 FROM sale_lines l "
                         "WHERE l.sale_id = s.id AND (l.name LIKE %s OR l.barcode = %s)))")
            like = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params += [like, like, text]
        sql = ("SELECT s.id, s.sale_no, s.created_at, s.item_count, s.subtotal, s.discount_total, "
               "s.total, s.cost_total, u.full_name AS cashier, "
               "(SELECT GROUP_CONCAT(DISTINCT pm.name ORDER BY pm.sort_order SEPARATOR ', ') "
               "   FROM sale_payments p JOIN payment_methods pm ON pm.id = p.payment_method_id "
               "  WHERE p.sale_id = s.id) AS methods "
               "FROM sales s JOIN users u ON u.id = s.cashier_id WHERE " + " AND ".join(where) +
               " ORDER BY s.id DESC LIMIT %s")
        params.append(int(limit))
        return self._all(sql, params, cur)

    def get_sale(self, sale_id: int, cur=None) -> dict | None:
        return self._one(
            "SELECT s.*, u.full_name AS cashier, a.full_name AS sale_discount_approver "
            "FROM sales s JOIN users u ON u.id = s.cashier_id "
            "LEFT JOIN users a ON a.id = s.sale_discount_approved_by WHERE s.id = %s",
            (sale_id,), cur)

    def get_lines(self, sale_id: int, cur=None) -> list[dict]:
        return self._all("SELECT l.*, a.full_name AS discount_approver FROM sale_lines l "
                         "LEFT JOIN users a ON a.id = l.discount_approved_by "
                         "WHERE l.sale_id = %s ORDER BY l.line_no", (sale_id,), cur)

    def get_payments(self, sale_id: int, cur=None) -> list[dict]:
        return self._all("SELECT p.*, pm.name AS method, pm.is_cash FROM sale_payments p "
                         "JOIN payment_methods pm ON pm.id = p.payment_method_id "
                         "WHERE p.sale_id = %s ORDER BY p.id", (sale_id,), cur)

    # ------------------------------------------------- payment methods
    def payment_methods(self, include_inactive: bool = False, cur=None) -> list[dict]:
        sql = "SELECT * FROM payment_methods"
        if not include_inactive:
            sql += " WHERE is_active = 1"
        return self._all(sql + " ORDER BY sort_order, name", (), cur)

    def get_payment_method(self, method_id: int, cur=None) -> dict | None:
        return self._one("SELECT * FROM payment_methods WHERE id = %s", (method_id,), cur)

    def find_payment_method(self, code: str, name: str, exclude_id: int | None, cur=None):
        return self._one("SELECT * FROM payment_methods WHERE (code = %s OR name = %s) AND id <> %s",
                         (code, name, exclude_id or 0), cur)

    def insert_payment_method(self, cur, code, name, requires_reference) -> int:
        row = self._one("SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM payment_methods", (), cur)
        return self._exec(cur, "INSERT INTO payment_methods (code, name, is_cash, requires_reference, "
                               "sort_order) VALUES (%s, %s, 0, %s, %s)",
                          (code, name, int(requires_reference), row["n"]))

    def update_payment_method(self, cur, method_id, name, requires_reference, is_active) -> None:
        self._exec(cur, "UPDATE payment_methods SET name = %s, requires_reference = %s, "
                        "is_active = %s WHERE id = %s",
                   (name, int(requires_reference), int(is_active), method_id))

    # ------------------------------------------------------ held sales
    def hold(self, cur, label, user_id, item_count, total, cart_json) -> int:
        return self._exec(cur, "INSERT INTO held_sales (label, held_by, item_count, total, cart_json) "
                               "VALUES (%s, %s, %s, %s, %s)",
                          (label, user_id, item_count, total, cart_json))

    def list_held(self, cur=None) -> list[dict]:
        return self._all("SELECT h.id, h.label, h.item_count, h.total, h.created_at, "
                         "u.full_name AS held_by FROM held_sales h JOIN users u ON u.id = h.held_by "
                         "ORDER BY h.id", (), cur)

    def take_held(self, cur, held_id: int) -> dict | None:
        row = self._one("SELECT * FROM held_sales WHERE id = %s FOR UPDATE", (held_id,), cur)
        if row:
            self._exec(cur, "DELETE FROM held_sales WHERE id = %s", (held_id,))
        return row

    def count_held(self, cur=None) -> int:
        return int(self._one("SELECT COUNT(*) AS n FROM held_sales", (), cur)["n"])

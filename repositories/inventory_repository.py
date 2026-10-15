"""SQL for the stock list, movement ledger, adjustments and stock counts."""
from __future__ import annotations

from datetime import date, timedelta

from repositories.base import Repository
from repositories.product_repository import _like

_STOCK_SELECT = """
SELECT p.id, p.sku, p.barcode, p.name, c.name AS category_name, u.code AS unit_code,
       u.allow_decimal AS unit_allow_decimal, p.cost_price, p.selling_price, p.reorder_level,
       p.is_active, COALESCE(s.quantity, 0) AS quantity
FROM products p
JOIN units u ON u.id = p.unit_id
LEFT JOIN categories c ON c.id = p.category_id
LEFT JOIN brands b ON b.id = p.brand_id
LEFT JOIN product_stock s ON s.product_id = p.id
"""


class InventoryRepository(Repository):
    # ------------------------------------------------------------ stock list
    def stock_list(self, *, text: str = "", category_id: int | None = None, low_only: bool = False,
                   include_inactive: bool = False, limit: int = 5000, cur=None) -> list[dict]:
        where, params = [], []
        if not include_inactive:
            where.append("p.is_active = 1")
        if category_id:
            where.append("p.category_id = %s")
            params.append(category_id)
        if low_only:
            where.append("COALESCE(s.quantity, 0) <= p.reorder_level")
        for word in (text or "").split()[:6]:
            like = _like(word)
            where.append("(p.name LIKE %s OR p.sku LIKE %s OR p.barcode LIKE %s OR b.name LIKE %s)")
            params += [like, like, like, like]
        sql = _STOCK_SELECT + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY p.name LIMIT %s"
        params.append(int(limit))
        return self._all(sql, params, cur)

    def totals(self, cur=None) -> dict:
        return self._one(
            "SELECT COUNT(*) AS products, "
            "COALESCE(SUM(CASE WHEN COALESCE(s.quantity, 0) > 0 "
            "             THEN s.quantity * p.cost_price ELSE 0 END), 0) AS value, "
            "COALESCE(SUM(COALESCE(s.quantity, 0) <= p.reorder_level), 0) AS low, "
            "COALESCE(SUM(COALESCE(s.quantity, 0) < 0), 0) AS negative "
            "FROM products p LEFT JOIN product_stock s ON s.product_id = p.id "
            "WHERE p.is_active = 1", (), cur)

    # --------------------------------------------------------------- ledger
    def movements(self, product_id: int, date_from: date | None = None,
                  date_to: date | None = None, limit: int = 2000, cur=None) -> list[dict]:
        where, params = ["m.product_id = %s"], [product_id]
        if date_from:
            where.append("m.created_at >= %s")
            params.append(date_from)
        if date_to:
            where.append("m.created_at < %s")
            params.append(date_to + timedelta(days=1))
        params.append(int(limit))
        return self._all(
            "SELECT m.id, m.created_at, m.movement_type, m.quantity, m.unit_cost, m.balance_after, "
            "m.reference_type, m.reference_id, m.note, u.full_name AS user_name "
            "FROM stock_movements m LEFT JOIN users u ON u.id = m.created_by "
            "WHERE " + " AND ".join(where) + " ORDER BY m.id DESC LIMIT %s", params, cur)

    def ledger_sum(self, product_id: int, cur=None) -> dict:
        return self._one("SELECT COALESCE(SUM(quantity), 0) AS total, COUNT(*) AS n "
                         "FROM stock_movements WHERE product_id = %s", (product_id,), cur)

    # ---------------------------------------------------------- adjustments
    def find_adjustment(self, token: str, cur=None) -> dict | None:
        return self._one("SELECT * FROM stock_adjustments WHERE client_token = %s", (token,), cur)

    def insert_adjustment(self, cur, *, token, product_id, quantity, reason, note, unit_cost,
                          user_id) -> int:
        return self._exec(cur, "INSERT INTO stock_adjustments (client_token, product_id, quantity, "
                               "reason, note, unit_cost, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                          (token, product_id, quantity, reason, note, unit_cost, user_id))

    # --------------------------------------------------------- stock counts
    def insert_count(self, cur, count_no: str, note: str | None, category_id: int | None,
                     user_id: int) -> int:
        return self._exec(cur, "INSERT INTO stock_counts (count_no, note, category_id, created_by) "
                               "VALUES (%s, %s, %s, %s)", (count_no, note, category_id, user_id))

    def add_count_lines(self, cur, count_id: int, category_id: int | None) -> int:
        sql = ("INSERT INTO stock_count_lines (count_id, product_id) "
               "SELECT %s, p.id FROM products p WHERE p.is_active = 1")
        params: list = [count_id]
        if category_id:
            sql += " AND p.category_id = %s"
            params.append(category_id)
        return self._exec(cur, sql, params)

    def list_counts(self, limit: int = 200, cur=None) -> list[dict]:
        return self._all(
            "SELECT c.id, c.count_no, c.status, c.note, c.created_at, c.posted_at, "
            "cat.name AS category_name, u.full_name AS created_by_name, "
            "pu.full_name AS posted_by_name, "
            "(SELECT COUNT(*) FROM stock_count_lines l WHERE l.count_id = c.id) AS line_count, "
            "(SELECT COUNT(*) FROM stock_count_lines l WHERE l.count_id = c.id "
            "   AND l.counted_qty IS NOT NULL) AS counted "
            "FROM stock_counts c JOIN users u ON u.id = c.created_by "
            "LEFT JOIN users pu ON pu.id = c.posted_by "
            "LEFT JOIN categories cat ON cat.id = c.category_id "
            "ORDER BY c.id DESC LIMIT %s", (int(limit),), cur)

    def get_count(self, count_id: int, cur=None, for_update: bool = False) -> dict | None:
        return self._one("SELECT * FROM stock_counts WHERE id = %s" + (" FOR UPDATE" if for_update else ""),
                         (count_id,), cur)

    def count_lines(self, count_id: int, cur=None) -> list[dict]:
        return self._all(
            "SELECT l.id, l.product_id, l.counted_qty, l.system_qty, l.difference, l.unit_cost, "
            "p.sku, p.barcode, p.name, u.code AS unit_code, u.allow_decimal AS unit_allow_decimal, "
            "p.cost_price, COALESCE(s.quantity, 0) AS current_qty "
            "FROM stock_count_lines l JOIN products p ON p.id = l.product_id "
            "JOIN units u ON u.id = p.unit_id LEFT JOIN product_stock s ON s.product_id = p.id "
            "WHERE l.count_id = %s ORDER BY p.name", (count_id,), cur)

    def set_counted(self, cur, count_id: int, product_id: int, qty) -> None:
        self._exec(cur, "UPDATE stock_count_lines SET counted_qty = %s "
                        "WHERE count_id = %s AND product_id = %s", (qty, count_id, product_id))

    def set_line_result(self, cur, line_id: int, system_qty, difference, unit_cost) -> None:
        self._exec(cur, "UPDATE stock_count_lines SET system_qty = %s, difference = %s, unit_cost = %s "
                        "WHERE id = %s", (system_qty, difference, unit_cost, line_id))

    def set_count_status(self, cur, count_id: int, status: str, user_id: int | None = None) -> None:
        if status == "posted":
            self._exec(cur, "UPDATE stock_counts SET status = 'posted', posted_by = %s, "
                            "posted_at = NOW() WHERE id = %s", (user_id, count_id))
        else:
            self._exec(cur, "UPDATE stock_counts SET status = %s WHERE id = %s", (status, count_id))

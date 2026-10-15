"""SQL for products and their price history."""
from __future__ import annotations

from decimal import Decimal

from repositories.base import Repository

_SELECT = """
SELECT p.id, p.sku, p.barcode, p.name, p.category_id, c.name AS category_name,
       p.brand_id, b.name AS brand_name, p.unit_id, u.code AS unit_code,
       u.allow_decimal AS unit_allow_decimal, p.cost_price, p.selling_price,
       p.reorder_level, p.track_expiry, p.is_active
FROM products p
JOIN units u ON u.id = p.unit_id
LEFT JOIN categories c ON c.id = p.category_id
LEFT JOIN brands b ON b.id = p.brand_id
"""


def _like(text: str) -> str:
    safe = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{safe}%"


class ProductRepository(Repository):
    def get(self, product_id: int, cur=None, for_update: bool = False) -> dict | None:
        return self._one(_SELECT + " WHERE p.id = %s" + (" FOR UPDATE" if for_update else ""),
                         (product_id,), cur)

    def get_by_barcode(self, code: str, cur=None) -> dict | None:
        return self._one(_SELECT + " WHERE p.barcode = %s", (code,), cur)

    def get_by_sku(self, sku: str, cur=None) -> dict | None:
        return self._one(_SELECT + " WHERE p.sku = %s", (sku,), cur)

    def search(self, *, text: str = "", category_id: int | None = None,
               include_inactive: bool = False, limit: int = 500, cur=None) -> list[dict]:
        where, params = [], []
        if not include_inactive:
            where.append("p.is_active = 1")
        if category_id:
            where.append("p.category_id = %s")
            params.append(category_id)
        order = "p.name"
        if text:
            # Every word must match somewhere (name, brand, SKU or barcode).
            for word in text.split()[:6]:
                like = _like(word)
                where.append("(p.name LIKE %s OR p.sku LIKE %s OR p.barcode LIKE %s "
                             "OR b.name LIKE %s)")
                params += [like, like, like, like]
            # Exact barcode / SKU matches first, then names starting with the text.
            order = ("(p.barcode = %s OR p.sku = %s) DESC, (p.name LIKE %s) DESC, p.name")
        sql = _SELECT + (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY {order}"
        if text:
            params += [text, text, _like(text)[1:]]  # 'abc%' = starts with
        sql += " LIMIT %s"
        params.append(int(limit))
        return self._all(sql, params, cur)

    def next_sku_number(self, cur) -> int:
        row = self._one("SELECT COALESCE(MAX(CAST(SUBSTRING(sku, 2) AS UNSIGNED)), 0) AS n "
                        "FROM products WHERE sku REGEXP '^P[0-9]+$' FOR UPDATE", (), cur)
        return int(row["n"]) + 1

    def insert(self, cur, *, sku, barcode, name, category_id, brand_id, unit_id, cost_price,
               selling_price, reorder_level, track_expiry, user_id) -> int:
        return self._exec(
            cur,
            "INSERT INTO products (sku, barcode, name, category_id, brand_id, unit_id, cost_price, "
            "selling_price, reorder_level, track_expiry, created_by, updated_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (sku, barcode, name, category_id, brand_id, unit_id, cost_price, selling_price,
             reorder_level, int(track_expiry), user_id, user_id),
        )

    def update(self, cur, product_id: int, *, sku, barcode, name, category_id, brand_id, unit_id,
               cost_price, selling_price, reorder_level, track_expiry, user_id) -> None:
        self._exec(
            cur,
            "UPDATE products SET sku = %s, barcode = %s, name = %s, category_id = %s, "
            "brand_id = %s, unit_id = %s, cost_price = %s, selling_price = %s, "
            "reorder_level = %s, track_expiry = %s, updated_by = %s WHERE id = %s",
            (sku, barcode, name, category_id, brand_id, unit_id, cost_price, selling_price,
             reorder_level, int(track_expiry), user_id, product_id),
        )

    def set_cost(self, cur, product_id: int, cost_price: Decimal, user_id: int) -> None:
        self._exec(cur, "UPDATE products SET cost_price = %s, updated_by = %s WHERE id = %s",
                   (cost_price, user_id, product_id))

    def set_active(self, cur, product_id: int, active: bool, user_id: int) -> None:
        self._exec(cur, "UPDATE products SET is_active = %s, updated_by = %s WHERE id = %s",
                   (int(active), user_id, product_id))

    def add_price_history(self, cur, product_id: int, old_cost: Decimal | None, new_cost: Decimal,
                          old_price: Decimal | None, new_price: Decimal, user_id: int,
                          reason: str) -> None:
        self._exec(
            cur,
            "INSERT INTO product_price_history (product_id, old_cost_price, new_cost_price, "
            "old_selling_price, new_selling_price, changed_by, reason) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (product_id, old_cost, new_cost, old_price, new_price, user_id, reason[:100]),
        )

    def price_history(self, product_id: int, cur=None) -> list[dict]:
        return self._all(
            "SELECT h.changed_at, u.full_name AS changed_by, h.old_cost_price, h.new_cost_price, "
            "h.old_selling_price, h.new_selling_price, h.reason "
            "FROM product_price_history h LEFT JOIN users u ON u.id = h.changed_by "
            "WHERE h.product_id = %s ORDER BY h.id DESC", (product_id,), cur)

    def count(self, cur=None) -> dict:
        return self._one("SELECT COUNT(*) AS total, COALESCE(SUM(is_active), 0) AS active "
                         "FROM products", (), cur)

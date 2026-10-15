"""SQL for stock balances and the stock movement ledger."""
from __future__ import annotations

from decimal import Decimal

from repositories.base import Repository


class StockRepository(Repository):
    def lock_products(self, cur, product_ids: list[int]) -> dict[int, dict]:
        """Lock product rows (cost, name) for the rest of the transaction."""
        if not product_ids:
            return {}
        ids = sorted(set(product_ids))  # same order everywhere avoids deadlocks
        rows = self._all(
            "SELECT p.id, p.name, p.cost_price, p.is_active, COALESCE(s.quantity, 0) AS stock "
            f"FROM products p LEFT JOIN product_stock s ON s.product_id = p.id "
            f"WHERE p.id IN ({', '.join(['%s'] * len(ids))}) ORDER BY p.id FOR UPDATE",
            ids, cur)
        return {int(r["id"]): r for r in rows}

    def change(self, cur, *, product_id: int, quantity: Decimal, movement_type: str,
               unit_cost: Decimal, reference_type: str | None, reference_id: int | None,
               note: str | None, user_id: int | None) -> Decimal:
        """Add (+) or remove (-) stock and record why. Returns the new balance."""
        self._exec(cur, "INSERT INTO product_stock (product_id, quantity) VALUES (%s, %s) "
                        "ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)",
                   (product_id, quantity))
        bal = Decimal(self._one("SELECT quantity FROM product_stock WHERE product_id = %s",
                                (product_id,), cur)["quantity"])
        self._exec(cur, "INSERT INTO stock_movements (product_id, movement_type, quantity, unit_cost, "
                        "balance_after, reference_type, reference_id, note, created_by) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                   (product_id, movement_type, quantity, unit_cost, bal, reference_type,
                    reference_id, note, user_id))
        return bal

    def balance(self, product_id: int, cur=None) -> Decimal:
        row = self._one("SELECT quantity FROM product_stock WHERE product_id = %s", (product_id,), cur)
        return Decimal(row["quantity"]) if row else Decimal("0")

    def movements_for(self, reference_type: str, reference_id: int, cur=None) -> list[dict]:
        return self._all("SELECT * FROM stock_movements WHERE reference_type = %s AND "
                         "reference_id = %s ORDER BY id", (reference_type, reference_id), cur)

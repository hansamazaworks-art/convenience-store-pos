"""SQL for suppliers and stock receipts (deliveries)."""
from __future__ import annotations

from datetime import date, timedelta

from repositories.base import Repository


class PurchasingRepository(Repository):
    # -------------------------------------------------------------- suppliers
    def suppliers(self, include_inactive: bool = True, cur=None) -> list[dict]:
        sql = ("SELECT s.*, (SELECT COUNT(*) FROM stock_receipts r WHERE r.supplier_id = s.id) "
               "AS receipts, (SELECT MAX(received_at) FROM stock_receipts r "
               "WHERE r.supplier_id = s.id) AS last_delivery FROM suppliers s")
        if not include_inactive:
            sql += " WHERE s.is_active = 1"
        return self._all(sql + " ORDER BY s.name", (), cur)

    def get_supplier(self, supplier_id: int, cur=None) -> dict | None:
        return self._one("SELECT * FROM suppliers WHERE id = %s", (supplier_id,), cur)

    def supplier_by_name(self, name: str, cur=None) -> dict | None:
        return self._one("SELECT * FROM suppliers WHERE name = %s", (name,), cur)

    def insert_supplier(self, cur, name, phone, note, user_id) -> int:
        return self._exec(cur, "INSERT INTO suppliers (name, phone, note, created_by) "
                               "VALUES (%s, %s, %s, %s)", (name, phone, note, user_id))

    def update_supplier(self, cur, supplier_id, name, phone, note, is_active) -> None:
        self._exec(cur, "UPDATE suppliers SET name = %s, phone = %s, note = %s, is_active = %s "
                        "WHERE id = %s", (name, phone, note, int(is_active), supplier_id))

    # --------------------------------------------------------------- receipts
    def find_by_token(self, token: str, cur=None) -> dict | None:
        return self._one("SELECT * FROM stock_receipts WHERE client_token = %s", (token,), cur)

    def insert_receipt(self, cur, *, receipt_no, token, supplier_id, reference, note, item_count,
                       total, user_id) -> int:
        return self._exec(cur, "INSERT INTO stock_receipts (receipt_no, client_token, supplier_id, "
                               "reference, note, item_count, total, received_by) "
                               "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                          (receipt_no, token, supplier_id, reference, note, item_count, total, user_id))

    def insert_line(self, cur, *, receipt_id, line_no, product_id, quantity, unit_cost, line_total,
                    old_cost, new_cost) -> None:
        self._exec(cur, "INSERT INTO stock_receipt_lines (receipt_id, line_no, product_id, quantity, "
                        "unit_cost, line_total, old_cost, new_cost) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                   (receipt_id, line_no, product_id, quantity, unit_cost, line_total, old_cost, new_cost))

    def search(self, date_from: date, date_to: date, supplier_id: int | None = None,
               limit: int = 1000, cur=None) -> list[dict]:
        where = ["r.received_at >= %s", "r.received_at < %s"]
        params: list = [date_from, date_to + timedelta(days=1)]
        if supplier_id:
            where.append("r.supplier_id = %s")
            params.append(supplier_id)
        params.append(int(limit))
        return self._all(
            "SELECT r.*, s.name AS supplier_name, u.full_name AS received_by_name, "
            "(SELECT COUNT(*) FROM stock_receipt_lines l WHERE l.receipt_id = r.id) AS line_count "
            "FROM stock_receipts r JOIN users u ON u.id = r.received_by "
            "LEFT JOIN suppliers s ON s.id = r.supplier_id WHERE " + " AND ".join(where) +
            " ORDER BY r.id DESC LIMIT %s", params, cur)

    def get_receipt(self, receipt_id: int, cur=None) -> dict | None:
        return self._one("SELECT r.*, s.name AS supplier_name, u.full_name AS received_by_name "
                         "FROM stock_receipts r JOIN users u ON u.id = r.received_by "
                         "LEFT JOIN suppliers s ON s.id = r.supplier_id WHERE r.id = %s",
                         (receipt_id,), cur)

    def get_lines(self, receipt_id: int, cur=None) -> list[dict]:
        return self._all("SELECT l.*, p.name, p.sku, u.code AS unit_code FROM stock_receipt_lines l "
                         "JOIN products p ON p.id = l.product_id JOIN units u ON u.id = p.unit_id "
                         "WHERE l.receipt_id = %s ORDER BY l.line_no", (receipt_id,), cur)

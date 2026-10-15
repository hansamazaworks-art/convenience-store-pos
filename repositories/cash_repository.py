"""SQL for shifts, cash movements and expenses."""
from __future__ import annotations

from datetime import date, timedelta

from repositories.base import Repository

_SHIFT_SELECT = ("SELECT sh.*, u.full_name AS user_name, c.full_name AS closed_by_name "
                 "FROM shifts sh JOIN users u ON u.id = sh.user_id "
                 "LEFT JOIN users c ON c.id = sh.closed_by ")


class CashRepository(Repository):
    # ------------------------------------------------------------------ shifts
    def open_shift_for(self, user_id: int, cur=None, lock: bool = False) -> dict | None:
        return self._one(_SHIFT_SELECT + "WHERE sh.open_user_id = %s" + (" FOR UPDATE" if lock else ""),
                         (user_id,), cur)

    def get_shift(self, shift_id: int, cur=None, lock: bool = False) -> dict | None:
        return self._one(_SHIFT_SELECT + "WHERE sh.id = %s" + (" FOR UPDATE" if lock else ""),
                         (shift_id,), cur)

    def insert_shift(self, cur, shift_no: str, user_id: int, opening_float) -> int:
        return self._exec(cur, "INSERT INTO shifts (shift_no, user_id, open_user_id, opening_float) "
                               "VALUES (%s, %s, %s, %s)", (shift_no, user_id, user_id, opening_float))

    def close_shift(self, cur, shift_id: int, *, closed_by: int, expected, counted, difference,
                    note) -> None:
        self._exec(cur, "UPDATE shifts SET status = 'closed', open_user_id = NULL, closed_at = NOW(), "
                        "closed_by = %s, expected_cash = %s, counted_cash = %s, difference = %s, "
                        "close_note = %s WHERE id = %s",
                   (closed_by, expected, counted, difference, note, shift_id))

    def list_shifts(self, date_from: date, date_to: date, user_id: int | None = None,
                    cur=None) -> list[dict]:
        where = ["sh.opened_at >= %s", "sh.opened_at < %s"]
        params: list = [date_from, date_to + timedelta(days=1)]
        if user_id:
            where.append("sh.user_id = %s")
            params.append(user_id)
        return self._all(_SHIFT_SELECT + "WHERE " + " AND ".join(where) + " ORDER BY sh.id DESC",
                         params, cur)

    def open_shifts(self, cur=None) -> list[dict]:
        return self._all(_SHIFT_SELECT + "WHERE sh.status = 'open' ORDER BY sh.id", (), cur)

    def shift_sales(self, shift_id: int, cur=None) -> dict:
        return self._one("SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total, "
                         "COALESCE(SUM(discount_total), 0) AS discounts "
                         "FROM sales WHERE shift_id = %s", (shift_id,), cur)

    def shift_payments(self, shift_id: int, cur=None) -> list[dict]:
        """Amount applied per payment method (cash = net of change)."""
        return self._all("SELECT pm.name, pm.is_cash, COALESCE(SUM(p.amount), 0) AS amount, "
                         "COUNT(*) AS n FROM sale_payments p JOIN sales s ON s.id = p.sale_id "
                         "JOIN payment_methods pm ON pm.id = p.payment_method_id "
                         "WHERE s.shift_id = %s GROUP BY pm.id, pm.name, pm.is_cash, pm.sort_order "
                         "ORDER BY pm.sort_order", (shift_id,), cur)

    def movement_totals(self, shift_id: int, cur=None) -> dict[str, object]:
        rows = self._all("SELECT kind, COALESCE(SUM(amount), 0) AS total FROM cash_movements "
                         "WHERE shift_id = %s GROUP BY kind", (shift_id,), cur)
        return {r["kind"]: r["total"] for r in rows}

    # ---------------------------------------------------------- cash movements
    def find_movement(self, token: str, cur=None) -> dict | None:
        return self._one("SELECT * FROM cash_movements WHERE client_token = %s", (token,), cur)

    def insert_movement(self, cur, *, token, shift_id, kind, amount, reason, user_id,
                        approved_by=None, reference_type=None, reference_id=None) -> int:
        return self._exec(cur, "INSERT INTO cash_movements (client_token, shift_id, kind, amount, reason, "
                               "reference_type, reference_id, created_by, approved_by) "
                               "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                          (token, shift_id, kind, amount, reason, reference_type, reference_id,
                           user_id, approved_by))

    def movements(self, shift_id: int, cur=None) -> list[dict]:
        return self._all("SELECT m.*, u.full_name AS user_name, a.full_name AS approved_by_name "
                         "FROM cash_movements m JOIN users u ON u.id = m.created_by "
                         "LEFT JOIN users a ON a.id = m.approved_by WHERE m.shift_id = %s "
                         "ORDER BY m.id", (shift_id,), cur)

    # --------------------------------------------------------------- expenses
    def categories(self, include_inactive: bool = False, cur=None) -> list[dict]:
        sql = "SELECT * FROM expense_categories"
        if not include_inactive:
            sql += " WHERE is_active = 1"
        return self._all(sql + " ORDER BY name = 'Others', name", (), cur)

    def category_by_name(self, name: str, cur=None) -> dict | None:
        return self._one("SELECT * FROM expense_categories WHERE name = %s", (name,), cur)

    def get_category(self, category_id: int, cur=None) -> dict | None:
        return self._one("SELECT * FROM expense_categories WHERE id = %s", (category_id,), cur)

    def insert_category(self, cur, name: str) -> int:
        return self._exec(cur, "INSERT INTO expense_categories (name) VALUES (%s)", (name,))

    def find_expense(self, token: str, cur=None) -> dict | None:
        return self._one("SELECT * FROM expenses WHERE client_token = %s", (token,), cur)

    def get_expense(self, expense_id: int, cur=None, lock: bool = False) -> dict | None:
        return self._one("SELECT e.*, c.name AS category FROM expenses e "
                         "JOIN expense_categories c ON c.id = e.category_id WHERE e.id = %s"
                         + (" FOR UPDATE" if lock else ""), (expense_id,), cur)

    def insert_expense(self, cur, *, token, category_id, description, amount, paid_from, shift_id,
                       expense_date, user_id, approved_by) -> int:
        return self._exec(cur, "INSERT INTO expenses (client_token, category_id, description, amount, "
                               "paid_from, shift_id, expense_date, created_by, approved_by) "
                               "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                          (token, category_id, description, amount, paid_from, shift_id,
                           expense_date, user_id, approved_by))

    def void_expense(self, cur, expense_id: int, reason: str, user_id: int) -> None:
        self._exec(cur, "UPDATE expenses SET status = 'void', void_reason = %s, voided_by = %s "
                        "WHERE id = %s", (reason, user_id, expense_id))

    def list_expenses(self, date_from: date, date_to: date, include_void: bool = True,
                      cur=None) -> list[dict]:
        sql = ("SELECT e.*, c.name AS category, u.full_name AS created_by_name, "
               "a.full_name AS approved_by_name, sh.shift_no FROM expenses e "
               "JOIN expense_categories c ON c.id = e.category_id "
               "JOIN users u ON u.id = e.created_by LEFT JOIN users a ON a.id = e.approved_by "
               "LEFT JOIN shifts sh ON sh.id = e.shift_id "
               "WHERE e.expense_date BETWEEN %s AND %s")
        if not include_void:
            sql += " AND e.status = 'active'"
        return self._all(sql + " ORDER BY e.expense_date DESC, e.id DESC", (date_from, date_to), cur)

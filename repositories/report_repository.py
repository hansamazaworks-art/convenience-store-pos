"""Read-only SQL for the dashboard and the daily summary report."""
from __future__ import annotations

from datetime import date, timedelta

from repositories.base import Repository


class ReportRepository(Repository):
    def sales_totals(self, day: date, cashier_id: int | None = None, cur=None) -> dict:
        sql = ("SELECT COUNT(*) AS n, COALESCE(SUM(item_count), 0) AS items, "
               "COALESCE(SUM(subtotal), 0) AS gross, COALESCE(SUM(discount_total), 0) AS discounts, "
               "COALESCE(SUM(total), 0) AS total, COALESCE(SUM(cost_total), 0) AS cost "
               "FROM sales WHERE created_at >= %s AND created_at < %s")
        params: list = [day, day + timedelta(days=1)]
        if cashier_id:
            sql += " AND cashier_id = %s"
            params.append(cashier_id)
        return self._one(sql, params, cur)

    def payments_by_method(self, day: date, cur=None) -> list[dict]:
        """Amount applied per payment method (cash = net of change)."""
        return self._all("SELECT pm.name, pm.is_cash, COALESCE(SUM(p.amount), 0) AS amount, "
                         "COUNT(*) AS n FROM sale_payments p JOIN sales s ON s.id = p.sale_id "
                         "JOIN payment_methods pm ON pm.id = p.payment_method_id "
                         "WHERE s.created_at >= %s AND s.created_at < %s "
                         "GROUP BY pm.id, pm.name, pm.is_cash, pm.sort_order ORDER BY pm.sort_order",
                         (day, day + timedelta(days=1)), cur)

    def expenses_by_category(self, day: date, cur=None) -> list[dict]:
        """Active (not voided) expenses of the day per category and where the money came from."""
        return self._all("SELECT c.name AS category, e.paid_from, COALESCE(SUM(e.amount), 0) AS amount, "
                         "COUNT(*) AS n FROM expenses e JOIN expense_categories c ON c.id = e.category_id "
                         "WHERE e.expense_date = %s AND e.status = 'active' "
                         "GROUP BY c.name, e.paid_from ORDER BY c.name, e.paid_from", (day,), cur)

    def deliveries(self, day: date, cur=None) -> dict:
        return self._one("SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total FROM stock_receipts "
                         "WHERE received_at >= %s AND received_at < %s",
                         (day, day + timedelta(days=1)), cur)

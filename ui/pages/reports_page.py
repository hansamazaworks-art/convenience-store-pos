"""Daily report: one day's sales, profit, expenses and cash, savable to Excel."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QDate
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDateEdit, QFileDialog, QGridLayout, QHBoxLayout, QLabel

from reports.excel import save_daily_summary
from services.report_service import DailySummary, summary_lines
from ui.pages.base import Page
from ui.widgets.common import button, card, info, label, run
from ui.widgets.tables import RED, fill_table, make_table
from utils.money import format_money


class DailyReportPage(Page):
    title = "Daily report"
    subtitle = "Sales, profit, expenses and cash for one day. Save it to Excel to keep or print."

    def __init__(self, services, session) -> None:
        super().__init__(services, session)
        self.symbol = "₱"
        self.summary: DailySummary | None = None
        bar = QHBoxLayout()
        self.day = QDateEdit(QDate.currentDate(), calendarPopup=True)
        self.day.setDisplayFormat("ddd, dd MMM yyyy")
        self.day.setMaximumDate(QDate.currentDate())
        self.day.dateChanged.connect(lambda _: self.refresh())
        bar.addWidget(button("◀ Previous day", lambda: self.day.setDate(self.day.date().addDays(-1))))
        bar.addWidget(self.day)
        bar.addWidget(button("Next day ▶", lambda: self.day.setDate(self.day.date().addDays(1))))
        bar.addWidget(button("Today", lambda: self.day.setDate(QDate.currentDate())))
        bar.addStretch()
        bar.addWidget(button("Save to Excel…", self.save_excel, "Primary"))
        self.lay.addLayout(bar)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.stats: dict[str, QLabel] = {}
        for i, (key, caption) in enumerate([("net_sales", "Net sales"), ("gross_profit", "Gross profit"),
                                             ("expenses", "Expenses"), ("net_profit", "Net profit")]):
            box, lay = card()
            lay.addWidget(label(caption, "Muted"))
            v = label("", "StatValue")
            lay.addWidget(v)
            self.stats[key] = v
            grid.addWidget(box, 0, i)
            box.setVisible(key in ("net_sales", "expenses") or self._see_cost())
        self.lay.addLayout(grid)

        self.table = make_table(["", "Amount"], stretch=0)
        self.lay.addWidget(self.table, 1)

    def _see_cost(self) -> bool:
        return self.services.products.can_see_cost(self.session)

    def on_show(self) -> None:
        ok, s = run(self, self.services.settings.get)
        if ok:
            self.symbol = s.currency_symbol
        self.refresh()

    def refresh(self) -> None:
        ok, summ = run(self, self.services.reports.daily_summary, self.session, self.day.date().toPython())
        if not ok:
            return
        self.summary = summ
        m = lambda v: format_money(v, self.symbol)  # noqa: E731
        self.stats["net_sales"].setText(m(summ.net_sales))
        self.stats["expenses"].setText(m(summ.expenses_total))
        if summ.cost is not None:
            self.stats["gross_profit"].setText(m(summ.gross_profit))
            self.stats["net_profit"].setText(m(summ.net_profit))
        lines = summary_lines(summ)
        fill_table(self.table, [[ln.label, m(ln.value) if isinstance(ln.value, Decimal) else ln.value]
                                for ln in lines], {1},
                   [RED if isinstance(ln.value, Decimal) and ln.value < 0 else None for ln in lines])
        bold = QFont()
        bold.setBold(True)
        for r, ln in enumerate(lines):
            if ln.is_heading or ln.bold:
                for c in range(2):
                    self.table.item(r, c).setFont(bold)

    def save_excel(self) -> None:
        if self.summary is None:
            return
        day: date = self.summary.day
        default = str(Path.home() / "Documents" / f"Daily report {day:%Y-%m-%d}.xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "Save daily report", default, "Excel files (*.xlsx)")
        if path:
            self.export_to(path)

    def export_to(self, path: str) -> Path | None:
        store = self.services.settings.get().store_name
        ok, saved = run(self, save_daily_summary, self.summary, path, store, self.symbol)
        if ok:
            info(self, "Saved", f"Daily report saved to:\n{saved}")
            return saved
        return None

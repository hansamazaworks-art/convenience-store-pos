"""Home page after login."""
from __future__ import annotations

from datetime import date, datetime

from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from ui.pages.base import Page
from ui.widgets.common import card, label, run
from utils.money import format_money

_MODULE_NAMES = {
    "dashboard": "Dashboard", "users": "User accounts", "settings": "Store settings",
    "audit": "Audit log", "pos": "Checkout & sales", "products": "Products",
    "inventory": "Inventory", "purchasing": "Suppliers & purchasing", "cash": "Cash & shifts",
    "expenses": "Expenses", "reports": "Reports", "shifts": "Cash & shifts",
    "suppliers": "Suppliers & purchasing",
}


def _n(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


class DashboardPage(Page):
    title = "Dashboard"

    def __init__(self, services, session) -> None:
        super().__init__(services, session)
        self.greeting = label("", "SectionTitle")
        self.lay.insertWidget(1, self.greeting)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.values: dict[str, QLabel] = {}
        for i, (key, caption) in enumerate([("store", "Store"), ("user", "Logged in as"),
                                             ("role", "Role"), ("today", "Today")]):
            box, lay = card()
            lay.addWidget(label(caption, "Muted"))
            v = label("", "StatValue", wrap=True)
            lay.addWidget(v)
            self.values[key] = v
            grid.addWidget(box, 0, i)
        self.lay.addLayout(grid)

        # Today at a glance: each tile is shown only if this user may see it.
        self.lay.addWidget(label("Today", "SectionTitle"))
        today = QGridLayout()
        today.setSpacing(14)
        self.tiles: dict[str, tuple[QWidget, QLabel]] = {}
        for i, (key, caption) in enumerate([("sales", "Sales today"), ("profit", "Gross profit today"),
                                             ("my_sales", "My sales today"), ("low", "Low stock items"),
                                             ("shifts", "Open shifts"), ("my_shift", "My shift")]):
            box, lay = card()
            lay.addWidget(label(caption, "Muted"))
            v = label("", "StatValue", wrap=True)
            lay.addWidget(v)
            box.hide()
            self.tiles[key] = (box, v)
            today.addWidget(box, 0, i)
        self.lay.addLayout(today)

        box, lay = card()
        lay.addWidget(label("What your account can do", "SectionTitle"))
        self.access = label("", wrap=True)
        lay.addWidget(self.access)
        self.lay.addWidget(box)
        self.lay.addStretch()

    def on_show(self) -> None:
        s = self.session
        hour = datetime.now().hour
        part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        self.greeting.setText(f"Good {part}, {s.full_name.split()[0]}!")
        self.values["store"].setText(self.services.settings.get().store_name)
        self.values["user"].setText(f"{s.full_name}\n({s.username})")
        self.values["role"].setText(s.role_name)
        self.values["today"].setText(datetime.now().strftime("%a, %d %b %Y"))
        modules = sorted({_MODULE_NAMES.get(p.split(".")[0], p) for p in s.permissions})
        self.access.setText("  •  ".join(modules))
        self.refresh_today()

    def _tile(self, key: str, text: str) -> None:
        box, value = self.tiles[key]
        value.setText(text)
        box.show()

    def refresh_today(self) -> None:
        ok, d = run(self, self.services.reports.dashboard, self.session, date.today())
        if not ok:
            return
        sym = self.services.settings.get().currency_symbol
        m = lambda v: format_money(v, sym)  # noqa: E731
        for box, _ in self.tiles.values():
            box.hide()
        if "sales_total" in d:
            self._tile("sales", f"{m(d['sales_total'])}\n{_n(d['sales_count'], 'sale')}")
        if "gross_profit" in d:
            self._tile("profit", m(d["gross_profit"]))
        if "my_sales_total" in d:
            self._tile("my_sales", f"{m(d['my_sales_total'])}\n{_n(d['my_sales_count'], 'sale')}")
        if "low_stock" in d:
            extra = f"\n{d['negative_stock']} below zero" if d["negative_stock"] else ""
            self._tile("low", f"{d['low_stock']}{extra}")
        if "open_shifts" in d:
            self._tile("shifts", f"{len(d['open_shifts'])}\n" + ", ".join(d["open_shifts"]))
        if "my_shift_open" in d:
            self._tile("my_shift", "Open" if d["my_shift_open"] else "Not open yet")

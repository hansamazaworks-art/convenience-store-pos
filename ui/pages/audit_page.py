"""Audit log viewer (read-only)."""
from __future__ import annotations

import json

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDateEdit, QHBoxLayout, QHeaderView, QLineEdit, QTableWidget,
    QTableWidgetItem,
)

from ui.pages.base import Page
from ui.widgets.common import button, label, run

LIMIT = 500
_COLUMNS = ["Date & time", "User", "What happened", "Record", "Details", "Computer"]

ACTION_LABELS = {
    "auth.login": "Logged in",
    "auth.logout": "Logged out",
    "auth.login_failed": "Failed login",
    "auth.login_blocked_locked": "Login refused (account locked)",
    "auth.login_blocked_inactive": "Login refused (account disabled)",
    "auth.password_changed": "Changed own password",
    "auth.approval_failed": "Failed approval attempt",
    "user.first_admin_created": "Administrator account created",
    "user.created": "User created",
    "user.updated": "User edited",
    "user.enabled": "User enabled",
    "user.disabled": "User disabled",
    "user.password_reset": "Password reset",
    "settings.updated": "Store settings changed",
}


def _details_text(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw
    parts = []
    for k, v in data.items():
        if isinstance(v, list) and len(v) == 2:
            parts.append(f"{k}: {v[0] or '(blank)'} → {v[1] or '(blank)'}" if v[0] != v[1] else f"{k}: {v[1]}")
        elif isinstance(v, bool):
            parts.append(f"{k}: {'yes' if v else 'no'}")
        else:
            parts.append(f"{k}: {v}")
    return "; ".join(parts)


class AuditPage(Page):
    title = "Audit log"
    subtitle = "A permanent record of logins and changes. Entries cannot be edited or deleted."

    def __init__(self, services, session) -> None:
        super().__init__(services, session)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit(placeholderText="Search user, action or details…")
        self.search.returnPressed.connect(self.refresh)
        self.date_from = QDateEdit(QDate.currentDate().addDays(-7), calendarPopup=True)
        self.date_to = QDateEdit(QDate.currentDate(), calendarPopup=True)
        for d in (self.date_from, self.date_to):
            d.setDisplayFormat("dd MMM yyyy")
        bar.addWidget(self.search, 1)
        bar.addWidget(label("From"))
        bar.addWidget(self.date_from)
        bar.addWidget(label("To"))
        bar.addWidget(self.date_to)
        bar.addWidget(button("Search", self.refresh, "Primary"))
        self.lay.addLayout(bar)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setWordWrap(False)
        hh = self.table.horizontalHeader()
        for i in range(len(_COLUMNS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lay.addWidget(self.table, 1)
        self.count = label("", "Muted")
        self.lay.addWidget(self.count)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        if self.date_from.date() > self.date_to.date():
            self.date_from.setDate(self.date_to.date())
        ok, rows = run(self, self.services.audit.search, self.session,
                       text=self.search.text(),
                       date_from=self.date_from.date().toPython(),
                       date_to=self.date_to.date().toPython(), limit=LIMIT)
        if not ok:
            return
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            record = f"{row['entity_type'] or ''} {row['entity_id'] or ''}".strip()
            values = [row["created_at"].strftime("%d %b %Y %H:%M:%S"), row["username"] or "—",
                      ACTION_LABELS.get(row["action"], row["action"]), record,
                      _details_text(row["details"]), row["workstation"] or ""]
            for c, v in enumerate(values):
                item = QTableWidgetItem(v)
                item.setToolTip(v)
                self.table.setItem(r, c, item)
        more = f" (showing the newest {LIMIT}; narrow the dates to see older ones)" \
            if len(rows) >= LIMIT else ""
        self.count.setText(f"{len(rows)} entries{more}")

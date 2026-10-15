"""User accounts (administrators)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from models.user import UserRecord
from ui.dialogs.account_dialogs import ResetPasswordDialog, UserDialog, show_temporary_password
from ui.pages.base import Page
from ui.widgets.common import button, button_row, confirm, run

_COLUMNS = ["Full name", "Username", "Role", "Status", "Last login"]


class UsersPage(Page):
    title = "Users"
    subtitle = ("Create accounts for each person. Everyone logs in with their own account, "
                "so every sale and change is recorded under their name.")

    def __init__(self, services, session) -> None:
        super().__init__(services, session)
        self.users: list[UserRecord] = []

        self.add_btn = button("+ Add user", self.add_user, "Primary", "Ctrl+N")
        self.edit_btn = button("Edit", self.edit_user)
        self.reset_btn = button("Reset password", self.reset_password)
        self.toggle_btn = button("Disable", self.toggle_active)
        self.lay.addLayout(button_row(self.add_btn, self.edit_btn, self.reset_btn,
                                      self.toggle_btn, stretch_first=False))

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setAlternatingRowColors(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(lambda _: self.edit_user())
        self.lay.addWidget(self.table, 1)
        self._update_buttons()

    # ---------------------------------------------------------------- data
    def on_show(self) -> None:
        self.refresh()

    def refresh(self, select_id: int | None = None) -> None:
        ok, users = run(self, self.services.users.list_users, self.session)
        if not ok:
            return
        current = select_id or (self.selected().id if self.selected() else None)
        self.users = users
        self.table.setRowCount(len(users))
        for row, u in enumerate(users):
            status = "Disabled" if not u.is_active else "Locked" if u.is_locked else (
                "Must change password" if u.must_change_password else "Active")
            values = [u.full_name, u.username, u.role_name, status,
                      u.last_login_at.strftime("%d %b %Y %H:%M") if u.last_login_at else "Never"]
            for col, v in enumerate(values):
                item = QTableWidgetItem(v)
                if not u.is_active:
                    item.setForeground(Qt.gray)
                self.table.setItem(row, col, item)
            if u.id == current:
                self.table.selectRow(row)
        self._update_buttons()

    def selected(self) -> UserRecord | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows or rows[0].row() >= len(self.users):
            return None
        return self.users[rows[0].row()]

    def _update_buttons(self) -> None:
        u = self.selected()
        for b in (self.edit_btn, self.reset_btn, self.toggle_btn):
            b.setEnabled(u is not None)
        self.toggle_btn.setText("Enable" if (u and not u.is_active) else "Disable")

    # ------------------------------------------------------------- actions
    def _roles(self):
        ok, roles = run(self, self.services.users.list_roles, self.session)
        return roles if ok else None

    def add_user(self) -> None:
        roles = self._roles()
        if roles is None:
            return
        dlg = UserDialog(self.services, self.session, roles, parent=self)
        if dlg.exec():
            show_temporary_password(self, dlg.username.text().strip(), dlg.created_password)
            self.refresh()

    def edit_user(self) -> None:
        u = self.selected()
        roles = self._roles() if u else None
        if u is None or roles is None:
            return
        if UserDialog(self.services, self.session, roles, user=u, parent=self).exec():
            self.refresh(u.id)

    def reset_password(self) -> None:
        u = self.selected()
        if u is None:
            return
        dlg = ResetPasswordDialog(self.services, self.session, u, parent=self)
        if dlg.exec():
            show_temporary_password(self, u.username, dlg.temp.text())
            self.refresh(u.id)

    def toggle_active(self) -> None:
        u = self.selected()
        if u is None:
            return
        enable = not u.is_active
        verb = "Enable" if enable else "Disable"
        text = (f"{verb} the account of {u.full_name} ({u.username})?" +
                ("" if enable else "\n\nThey will no longer be able to log in. "
                 "Their past records are kept."))
        if confirm(self, f"{verb} user", text, verb):
            ok, _ = run(self, self.services.users.set_active, self.session, u.id, enable)
            if ok:
                self.refresh(u.id)

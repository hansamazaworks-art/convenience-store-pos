"""Dialogs for first-time setup, changing passwords and managing users."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget,
)

from models.user import Role, Session, UserRecord
from services.container import Services
from services.errors import ValidationError
from ui.widgets.common import (
    button, button_row, error_message, generate_temporary_password, info, label, password_field,
)
from utils.security import MIN_PASSWORD_LENGTH


class _FormDialog(QDialog):
    """Base: title, intro text, a form, an inline error box and OK/Cancel."""

    def __init__(self, parent: QWidget | None, title: str, intro: str, ok_text: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(24, 20, 24, 20)
        self.lay.setSpacing(12)
        self.lay.addWidget(label(title, "SectionTitle"))
        if intro:
            self.lay.addWidget(label(intro, "Muted", wrap=True))
        self.form = QFormLayout()
        self.form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        self.form.setVerticalSpacing(6)
        self.lay.addLayout(self.form)
        self.error = label("", "ErrorBox", wrap=True)
        self.error.hide()
        self.lay.addWidget(self.error)
        self.cancel_btn = button("Cancel", self.reject)
        self.ok_btn = button(ok_text, self._on_ok, "Primary")
        self.ok_btn.setDefault(True)
        self.lay.addLayout(button_row(self.cancel_btn, self.ok_btn))

    def fail(self, exc_or_text) -> None:
        msg = exc_or_text if isinstance(exc_or_text, str) else error_message(exc_or_text)[1]
        self.error.setText(msg)
        self.error.show()

    def _on_ok(self) -> None:
        self.error.hide()
        try:
            self.submit()
        except Exception as exc:  # noqa: BLE001
            self.fail(exc)
            return
        self.accept()

    def submit(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


def _check_match(a: QLineEdit, b: QLineEdit) -> None:
    if a.text() != b.text():
        raise ValidationError("The two passwords do not match.")


class FirstAdminDialog(_FormDialog):
    """Shown once, when the database has no users yet."""

    def __init__(self, services: Services, parent: QWidget | None = None) -> None:
        super().__init__(
            parent, "Welcome - create the administrator account",
            "This is the first time the POS is used. Create the main administrator "
            "account (usually the store owner). Keep this password safe: it can manage "
            "all users and settings.",
            "Create account and log in",
        )
        self.services = services
        self.session: Session | None = None
        self.full_name = QLineEdit(placeholderText="e.g. Maria Santos")
        self.username = QLineEdit(placeholderText="e.g. owner")
        self.pw1 = password_field(f"At least {MIN_PASSWORD_LENGTH} characters")
        self.pw2 = password_field("Type it again")
        self.form.addRow("Your full name", self.full_name)
        self.form.addRow("Username (used to log in)", self.username)
        self.form.addRow("Password", self.pw1)
        self.form.addRow("Confirm password", self.pw2)
        self.full_name.setFocus()

    def submit(self) -> None:
        _check_match(self.pw1, self.pw2)
        self.session = self.services.auth.create_first_admin(
            self.username.text(), self.full_name.text(), self.pw1.text())


class ChangePasswordDialog(_FormDialog):
    def __init__(self, services: Services, session: Session, parent: QWidget | None = None,
                 forced: bool = False) -> None:
        intro = ("You are using a temporary password. Choose your own password to continue."
                 if forced else "Choose a new password for your account.")
        super().__init__(parent, "Change your password", intro, "Change password")
        self.services = services
        self.session = session
        self.current = password_field("Your current (or temporary) password")
        self.pw1 = password_field(f"At least {MIN_PASSWORD_LENGTH} characters")
        self.pw2 = password_field("Type it again")
        self.form.addRow("Current password", self.current)
        self.form.addRow("New password", self.pw1)
        self.form.addRow("Confirm new password", self.pw2)
        if forced:
            self.cancel_btn.setText("Log out")
        self.current.setFocus()

    def submit(self) -> None:
        _check_match(self.pw1, self.pw2)
        self.session = self.services.auth.change_own_password(
            self.session, self.current.text(), self.pw1.text())


class _TempPasswordRow(QWidget):
    """A visible temporary-password field with a 'Generate' button."""

    def __init__(self) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.field = QLineEdit(generate_temporary_password())
        self.field.setMaxLength(72)
        row.addWidget(self.field, 1)
        row.addWidget(button("Generate", lambda: self.field.setText(generate_temporary_password())))

    def text(self) -> str:
        return self.field.text()


class UserDialog(_FormDialog):
    """Create a new user, or edit name/role of an existing one."""

    def __init__(self, services: Services, session: Session, roles: list[Role],
                 user: UserRecord | None = None, parent: QWidget | None = None) -> None:
        editing = user is not None
        super().__init__(
            parent,
            "Edit user" if editing else "Add user",
            ("Change the person's name or role." if editing else
             "The person must change the temporary password the first time they log in. "
             "Write it down and give it to them."),
            "Save" if editing else "Create user",
        )
        self.services, self.session, self.user = services, session, user
        self.created_password: str | None = None
        self.username = QLineEdit(user.username if user else "")
        self.username.setMaxLength(50)
        self.username.setReadOnly(editing)
        self.full_name = QLineEdit(user.full_name if user else "")
        self.full_name.setMaxLength(100)
        self.role = QComboBox()
        for r in roles:
            self.role.addItem(f"{r.name} - {r.description}", r.id)
        if user:
            self.role.setCurrentIndex(max(0, self.role.findData(user.role_id)))
        else:
            cashier = next((i for i, r in enumerate(roles) if r.code == "cashier"), 0)
            self.role.setCurrentIndex(cashier)
        self.form.addRow("Full name", self.full_name)
        self.form.addRow("Username" + (" (cannot be changed)" if editing else ""), self.username)
        self.form.addRow("Role", self.role)
        self.temp: _TempPasswordRow | None = None
        if not editing:
            self.temp = _TempPasswordRow()
            self.form.addRow("Temporary password", self.temp)
        (self.full_name if editing else self.full_name).setFocus()

    def submit(self) -> None:
        if self.user:
            self.services.users.update_user(self.session, self.user.id,
                                            full_name=self.full_name.text(),
                                            role_id=self.role.currentData())
        else:
            self.services.users.create_user(self.session, username=self.username.text(),
                                            full_name=self.full_name.text(),
                                            role_id=self.role.currentData(),
                                            temporary_password=self.temp.text())
            self.created_password = self.temp.text()


class ResetPasswordDialog(_FormDialog):
    def __init__(self, services: Services, session: Session, user: UserRecord,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            parent, f"Reset password - {user.full_name}",
            f"'{user.username}' will get this temporary password and must choose a new one "
            "at the next login. This also unlocks the account if it was locked.",
            "Reset password",
        )
        self.services, self.session, self.user = services, session, user
        self.temp = _TempPasswordRow()
        self.form.addRow("Temporary password", self.temp)

    def submit(self) -> None:
        self.services.users.reset_password(self.session, self.user.id, self.temp.text())


def show_temporary_password(parent: QWidget, username: str, password: str) -> None:
    info(parent, "Give this to the user",
         f"Username:  {username}\nTemporary password:  {password}\n\n"
         "They will be asked to choose their own password when they log in.")

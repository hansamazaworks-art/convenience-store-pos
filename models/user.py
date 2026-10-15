"""Plain data objects passed between layers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from services.errors import PermissionDenied


@dataclass(frozen=True)
class Role:
    id: int
    code: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class UserRecord:
    id: int
    username: str
    full_name: str
    role_id: int
    role_code: str
    role_name: str
    is_active: bool
    must_change_password: bool
    is_locked: bool
    last_login_at: datetime | None
    created_at: datetime | None

    @classmethod
    def from_row(cls, r: dict) -> "UserRecord":
        return cls(
            id=int(r["id"]), username=r["username"], full_name=r["full_name"],
            role_id=int(r["role_id"]), role_code=r["role_code"], role_name=r["role_name"],
            is_active=bool(r["is_active"]), must_change_password=bool(r["must_change_password"]),
            is_locked=bool(r.get("is_locked")), last_login_at=r.get("last_login_at"),
            created_at=r.get("created_at"),
        )


@dataclass(frozen=True)
class Session:
    """The person currently logged in, and what they may do."""
    user_id: int
    username: str
    full_name: str
    role_code: str
    role_name: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    must_change_password: bool = False

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, permission: str, action: str = "do this") -> None:
        if permission not in self.permissions:
            raise PermissionDenied(
                f"Your account ({self.role_name}) is not allowed to {action}.\n"
                "Ask a manager or administrator."
            )

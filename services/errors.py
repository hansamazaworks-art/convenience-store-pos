"""Errors raised by services. Each carries a message a store operator can read."""


class ServiceError(Exception):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class ValidationError(ServiceError):
    """The input is not acceptable (empty name, bad price, ...)."""


class PermissionDenied(ServiceError):
    """The logged-in user is not allowed to do this."""


class AuthError(ServiceError):
    """Login / password problem."""


class NotFound(ServiceError):
    """The record no longer exists."""

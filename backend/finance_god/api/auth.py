from collections.abc import Awaitable, Callable

from starlette.requests import Request


class AuthenticationError(PermissionError):
    """Bearer credentials are missing or invalid at the HTTP boundary."""


OwnerResolver = Callable[[Request], Awaitable[str]]

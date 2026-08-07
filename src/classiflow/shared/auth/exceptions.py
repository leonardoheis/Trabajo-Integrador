from dataclasses import dataclass


class AuthError(Exception):
    """Base exception for all authentication-related errors."""


@dataclass
class ExpiredTokenError(AuthError):
    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return "Token has expired"


@dataclass
class InvalidTokenError(AuthError):
    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return "Invalid token"

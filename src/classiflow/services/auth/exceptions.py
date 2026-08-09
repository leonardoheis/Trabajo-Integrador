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


@dataclass
class OAuthError(AuthError):
    message: str = "OAuth exchange failed"

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return self.message


@dataclass
class NotAllowedError(AuthError):
    email: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.email} is not in the allowed users list"

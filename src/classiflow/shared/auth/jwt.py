from datetime import datetime, timedelta, timezone
from typing import Any

from jose import ExpiredSignatureError, JWTError, jwt

from classiflow.settings import settings


class AuthError(Exception):
    pass


def encode_token(email: str) -> str:
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub": email,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")  # type: ignore[no-any-return]


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])  # type: ignore[no-any-return]
    except ExpiredSignatureError as exc:
        msg = "Token has expired"
        raise AuthError(msg) from exc
    except JWTError as exc:
        msg = "Invalid token"
        raise AuthError(msg) from exc

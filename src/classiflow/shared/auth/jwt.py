from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from classiflow.settings import Settings


class AuthError(Exception):
    pass


def encode_token(email: str) -> str:
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub": email,
        "iat": now,
        "exp": now + timedelta(minutes=Settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, Settings.JWT_SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, Settings.JWT_SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        msg = "Token has expired"
        raise AuthError(msg) from exc
    except jwt.InvalidTokenError as exc:
        msg = "Invalid token"
        raise AuthError(msg) from exc

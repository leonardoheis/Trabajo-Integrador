from datetime import datetime, timedelta, timezone

import jwt
from pydantic import BaseModel

from classiflow.services.auth.exceptions import ExpiredTokenError, InvalidTokenError
from classiflow.settings import Settings


class DecodedPayload(BaseModel):
    sub: str
    iat: int
    exp: int


def encode_token(email: str) -> str:
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": email,
        "iat": now,
        "exp": now + timedelta(minutes=Settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, Settings.JWT_SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> DecodedPayload:
    try:
        data = jwt.decode(token, Settings.JWT_SECRET_KEY, algorithms=["HS256"])
        return DecodedPayload.model_validate(data)
    except jwt.ExpiredSignatureError as exc:
        raise ExpiredTokenError from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError from exc

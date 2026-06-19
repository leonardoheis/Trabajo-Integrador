from datetime import datetime, timedelta, timezone

import jwt
import pytest

from classiflow.settings import settings
from classiflow.shared.auth.jwt import AuthError, decode_token, encode_token


def test_valid_token() -> None:
    email = "user@example.com"
    token = encode_token(email)
    payload = decode_token(token)
    assert payload["sub"] == email


def test_expired_token() -> None:
    email = "user@example.com"
    past = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
    payload: dict[str, object] = {"sub": email, "exp": past}
    token: str = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")
    with pytest.raises(AuthError):
        decode_token(token)


def test_tampered_signature() -> None:
    email = "user@example.com"
    token = encode_token(email)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(AuthError):
        decode_token(tampered)

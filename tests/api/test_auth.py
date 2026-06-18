from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from classiflow.settings import settings
from classiflow.shared.auth.jwt import AuthError, decode_token, encode_token

pytestmark = pytest.mark.anyio


async def test_valid_token() -> None:  # noqa: RUF029
    email = "user@example.com"
    token = encode_token(email)
    payload = decode_token(token)
    assert payload["sub"] == email


async def test_expired_token() -> None:  # noqa: RUF029
    email = "user@example.com"
    past = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
    payload = {"sub": email, "exp": past}
    token: str = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")
    with pytest.raises(AuthError):
        decode_token(token)


async def test_tampered_signature() -> None:  # noqa: RUF029
    email = "user@example.com"
    token = encode_token(email)
    # Flip the last character to corrupt the signature
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(AuthError):
        decode_token(tampered)

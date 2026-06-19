from datetime import datetime, timedelta, timezone

import jwt
import pytest

from classiflow.settings import Settings
from classiflow.shared.auth.jwt import AuthError, decode_token, encode_token

pytestmark = pytest.mark.usefixtures("_jwt_secret")


def test_valid_token() -> None:
    email = "user@example.com"
    token = encode_token(email)
    payload = decode_token(token)
    assert payload["sub"] == email


def test_expired_token() -> None:
    email = "user@example.com"
    past = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
    payload: dict[str, object] = {"sub": email, "exp": past}
    token: str = jwt.encode(payload, Settings.JWT_SECRET_KEY, algorithm="HS256")
    with pytest.raises(AuthError):
        decode_token(token)


def test_tampered_signature() -> None:
    email = "user@example.com"
    token = encode_token(email)
    header, payload, sig = token.split(".")
    # Change the first character of the signature — it encodes the most significant
    # bits of the first digest byte and is always effective, unlike the last character
    # which may only affect base64 padding bits.
    tampered_sig = ("B" if sig[0] != "B" else "C") + sig[1:]
    with pytest.raises(AuthError):
        decode_token(f"{header}.{payload}.{tampered_sig}")

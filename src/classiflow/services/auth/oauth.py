from urllib.parse import urlencode

import httpx

from classiflow.domain.repositories.user import IUserRepository
from classiflow.domain.user import AuthToken
from classiflow.services.auth.exceptions import NotAllowedError, OAuthError
from classiflow.services.auth.jwt import encode_token
from classiflow.settings import Settings

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_GRANT_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def get_authorization_url() -> str:
    params = {
        "client_id": Settings.GOOGLE_CLIENT_ID,
        "redirect_uri": Settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email",
        "access_type": "offline",
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


async def _fetch_email(client: httpx.AsyncClient, code: str) -> str:
    token_resp = await client.post(
        _GOOGLE_GRANT_URL,
        data={
            "code": code,
            "client_id": Settings.GOOGLE_CLIENT_ID,
            "client_secret": Settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": Settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
    )
    if token_resp.status_code != httpx.codes.OK:
        raise OAuthError(message=f"token endpoint returned {token_resp.status_code}")

    google_access: str = token_resp.json()["access_token"]

    info_resp = await client.get(
        _USERINFO_URL,
        headers={"Authorization": f"Bearer {google_access}"},
    )
    if info_resp.status_code != httpx.codes.OK:
        raise OAuthError(message=f"userinfo endpoint returned {info_resp.status_code}")

    return str(info_resp.json()["email"])


async def exchange_code(
    code: str,
    user_repo: IUserRepository,
    *,
    http: httpx.AsyncClient | None = None,
) -> AuthToken:
    should_close = http is None
    client = http or httpx.AsyncClient()
    try:
        email = await _fetch_email(client, code)
    except httpx.HTTPError as exc:
        raise OAuthError(message="Google request failed") from exc
    finally:
        if should_close:
            await client.aclose()

    if not await user_repo.is_allowed(email):
        raise NotAllowedError(email=email)

    return AuthToken(access_token=encode_token(email))

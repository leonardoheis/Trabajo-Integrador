from http import HTTPStatus
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from classiflow.database.models import AllowedUser
from classiflow.database.repositories.user import InMemoryUserRepository
from classiflow.domain.user import AuthToken
from classiflow.services.auth import decode_token, encode_token
from classiflow.services.auth.exceptions import NotAllowedError, OAuthError
from classiflow.services.auth.oauth import exchange_code, get_authorization_url
from classiflow.services.auth.service import AuthService
from classiflow.settings import Settings

pytestmark = pytest.mark.usefixtures("_jwt_secret")

_ALLOWED_EMAIL = "allowed@classiflow.dev"
_BLOCKED_EMAIL = "blocked@classiflow.dev"
_CALLBACK_EMAIL = "callback@classiflow.dev"


@pytest.fixture
def user_repo() -> InMemoryUserRepository:
    repo = InMemoryUserRepository()
    repo.seed(AllowedUser(email=_ALLOWED_EMAIL, is_active=True, is_blocked=False))
    repo.seed(AllowedUser(email=_BLOCKED_EMAIL, is_active=False, is_blocked=True))
    return repo


def _mock_transport(email: str = _ALLOWED_EMAIL) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        if "googleapis.com/token" in str(_request.url):
            return httpx.Response(httpx.codes.OK, json={"access_token": "google-at"})
        return httpx.Response(httpx.codes.OK, json={"email": email})

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# get_authorization_url
# ---------------------------------------------------------------------------


class TestGetAuthorizationUrl:
    def test_points_to_google(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Settings, "GOOGLE_CLIENT_ID", "my-client")
        assert "accounts.google.com" in get_authorization_url()

    def test_contains_client_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Settings, "GOOGLE_CLIENT_ID", "my-client")
        assert "my-client" in get_authorization_url()

    def test_requests_email_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Settings, "GOOGLE_CLIENT_ID", "x")
        url = get_authorization_url()
        assert "openid" in url
        assert "email" in url


# ---------------------------------------------------------------------------
# exchange_code (unit — uses MockTransport directly)
# ---------------------------------------------------------------------------


class TestExchangeCode:
    async def test_happy_path_returns_auth_token(self, user_repo: InMemoryUserRepository) -> None:
        async with httpx.AsyncClient(transport=_mock_transport()) as http:
            result = await exchange_code("auth-code", user_repo, http=http)
        assert isinstance(result, AuthToken)
        assert decode_token(result.access_token).sub == _ALLOWED_EMAIL

    async def test_raises_not_allowed_for_unknown_email(self) -> None:
        repo = InMemoryUserRepository()
        with pytest.raises(NotAllowedError):
            async with httpx.AsyncClient(transport=_mock_transport("nobody@test.com")) as http:
                await exchange_code("auth-code", repo, http=http)

    async def test_raises_oauth_error_on_bad_grant_response(
        self, user_repo: InMemoryUserRepository
    ) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(httpx.codes.BAD_REQUEST, json={"error": "invalid_grant"})

        with pytest.raises(OAuthError):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                await exchange_code("bad-code", user_repo, http=http)

    async def test_raises_oauth_error_on_bad_userinfo_response(
        self, user_repo: InMemoryUserRepository
    ) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            if "googleapis.com/token" in str(_request.url):
                return httpx.Response(httpx.codes.OK, json={"access_token": "tok"})
            return httpx.Response(httpx.codes.UNAUTHORIZED)

        with pytest.raises(OAuthError):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                await exchange_code("code", user_repo, http=http)


# ---------------------------------------------------------------------------
# AuthService
# ---------------------------------------------------------------------------


class TestAuthService:
    async def test_verify_valid_token_for_allowed_user(
        self, user_repo: InMemoryUserRepository
    ) -> None:
        service = AuthService(user_repo=user_repo)
        user = await service.verify_token(encode_token(_ALLOWED_EMAIL))
        assert user.email == _ALLOWED_EMAIL

    async def test_verify_raises_not_allowed_for_blocked_user(
        self, user_repo: InMemoryUserRepository
    ) -> None:
        service = AuthService(user_repo=user_repo)
        with pytest.raises(NotAllowedError):
            await service.verify_token(encode_token(_BLOCKED_EMAIL))

    async def test_verify_raises_for_unknown_user(self, user_repo: InMemoryUserRepository) -> None:
        service = AuthService(user_repo=user_repo)
        with pytest.raises(NotAllowedError):
            await service.verify_token(encode_token("nobody@test.com"))


# ---------------------------------------------------------------------------
# /auth/login endpoint
# ---------------------------------------------------------------------------


class TestAuthLoginEndpoint:
    def test_redirects_to_google(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Settings, "GOOGLE_CLIENT_ID", "test-id")
        response = client.get("/auth/login", follow_redirects=False)
        assert response.status_code == HTTPStatus.FOUND
        assert "accounts.google.com" in response.headers["location"]


# ---------------------------------------------------------------------------
# /auth/callback endpoint
# ---------------------------------------------------------------------------


class TestAuthCallbackEndpoint:
    def test_callback_returns_bearer_token(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        expected_jwt = encode_token(_CALLBACK_EMAIL)
        monkeypatch.setattr(
            "classiflow.api.routes.auth.endpoints.exchange_code",
            AsyncMock(return_value=AuthToken(access_token=expected_jwt)),
        )
        response = client.get("/auth/callback?code=google-code")
        assert response.status_code == HTTPStatus.OK
        result = AuthToken.model_validate(response.json())
        assert decode_token(result.access_token).sub == _CALLBACK_EMAIL

    def test_callback_not_allowed_returns_403(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "classiflow.api.routes.auth.endpoints.exchange_code",
            AsyncMock(side_effect=NotAllowedError(email="stranger@test.com")),
        )
        response = client.get("/auth/callback?code=google-code")
        assert response.status_code == HTTPStatus.FORBIDDEN

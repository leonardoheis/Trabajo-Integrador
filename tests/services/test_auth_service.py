import pytest

from classiflow.database.models import AllowedUser
from classiflow.database.repositories.user import InMemoryUserRepository
from classiflow.services.auth import encode_token
from classiflow.services.auth.service import AuthService

pytestmark = pytest.mark.usefixtures("_jwt_secret")


class TestAuthServiceIsAdmin:
    async def test_verify_token_populates_is_admin_true(self) -> None:
        repo = InMemoryUserRepository()
        repo.seed(AllowedUser(email="admin@example.com", is_active=True, is_admin=True))
        service = AuthService(repo)

        user = await service.verify_token(encode_token("admin@example.com"))

        assert user.is_admin is True

    async def test_verify_token_populates_is_admin_false(self) -> None:
        repo = InMemoryUserRepository()
        repo.seed(AllowedUser(email="user@example.com", is_active=True, is_admin=False))
        service = AuthService(repo)

        user = await service.verify_token(encode_token("user@example.com"))

        assert user.is_admin is False

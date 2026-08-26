from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("_jwt_secret")


class TestUsersEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/users")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_requires_admin(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        response = client.get("/users", headers=auth_headers)
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_admin_can_list_users(
        self, client: TestClient, admin_auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/users", headers=admin_auth_headers)
        assert response.status_code == HTTPStatus.OK
        assert isinstance(response.json(), list)

    def test_admin_can_create_user(
        self, client: TestClient, admin_auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/users",
            json={"email": "new@example.com", "isAdmin": False},
            headers=admin_auth_headers,
        )
        assert response.status_code == HTTPStatus.CREATED
        assert response.json()["email"] == "new@example.com"

    def test_admin_can_update_user(
        self, client: TestClient, admin_auth_headers: dict[str, str]
    ) -> None:
        client.post(
            "/users",
            json={"email": "toblock@example.com", "isAdmin": False},
            headers=admin_auth_headers,
        )
        response = client.patch(
            "/users/toblock@example.com",
            json={"isBlocked": True},
            headers=admin_auth_headers,
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["isBlocked"] is True

    def test_update_unknown_user_returns_404(
        self, client: TestClient, admin_auth_headers: dict[str, str]
    ) -> None:
        response = client.patch(
            "/users/nobody@example.com",
            json={"isBlocked": True},
            headers=admin_auth_headers,
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_admin_can_delete_user(
        self, client: TestClient, admin_auth_headers: dict[str, str]
    ) -> None:
        client.post(
            "/users",
            json={"email": "todelete@example.com", "isAdmin": False},
            headers=admin_auth_headers,
        )
        response = client.delete("/users/todelete@example.com", headers=admin_auth_headers)
        assert response.status_code == HTTPStatus.NO_CONTENT

        listing = client.get("/users", headers=admin_auth_headers).json()
        assert "todelete@example.com" not in [u["email"] for u in listing]

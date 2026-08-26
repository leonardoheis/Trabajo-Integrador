from http import HTTPStatus

import pytest
from fastapi import HTTPException

from classiflow.api.dependencies import require_admin
from classiflow.domain.user import User


class TestRequireAdmin:
    def test_raises_403_for_non_admin(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            require_admin(User(email="user@example.com", is_admin=False))
        assert exc_info.value.status_code == HTTPStatus.FORBIDDEN

    def test_passes_for_admin(self) -> None:
        require_admin(User(email="admin@example.com", is_admin=True))

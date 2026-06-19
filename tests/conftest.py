import pytest

from classiflow.settings import settings


@pytest.fixture
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "test-secret-key-for-testing-only-32chars!")

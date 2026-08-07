import pytest

from classiflow.settings import Settings


@pytest.fixture
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Settings, "JWT_SECRET_KEY", "test-secret-key-for-testing-only-32chars!")

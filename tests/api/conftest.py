import pytest
from fastapi.testclient import TestClient

from classiflow.api.app import create_app
from classiflow.injections import configure_container
from classiflow.injections.test import TestContainer
from classiflow.shared.auth import encode_token

_TEST_EMAIL = "test@classiflow.dev"


@pytest.fixture(scope="module")
def client() -> TestClient:
    configure_container.cache_clear()
    container = TestContainer()
    container.wire(packages=["classiflow"])
    return TestClient(create_app())


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {encode_token(_TEST_EMAIL)}"}

import pytest
from fastapi.testclient import TestClient

from classiflow.api.app import create_app
from classiflow.injections.test import TestContainer
from classiflow.services.auth import encode_token

_TEST_EMAIL = "test@classiflow.dev"


@pytest.fixture(scope="module")
def client() -> TestClient:
    TestContainer().wire(packages=["classiflow"])
    return TestClient(create_app())


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {encode_token(_TEST_EMAIL)}"}

import pytest
from fastapi.testclient import TestClient

from classiflow.api.app import create_app
from classiflow.database.models import AllowedUser
from classiflow.injections.production import Container
from classiflow.injections.test import TestContainer
from classiflow.services.auth import encode_token

_TEST_EMAIL = "test@classiflow.dev"


@pytest.fixture(scope="module")
def client() -> TestClient:
    # `Provide[Container.x]` markers throughout the app reference the *production*
    # Container class by identity, so wiring a same-named but unrelated TestContainer
    # instance can't satisfy them (dependency_injector's wiring maps providers by name
    # within one declarative class, not across two independent classes). Overriding a
    # Container() instance with a fresh TestContainer() instance keeps the exact provider
    # objects the markers point at, while swapping in the in-memory implementations.
    test_container = TestContainer()
    container = Container()
    container.override(test_container)
    container.wire(packages=["classiflow"])

    # `auth_headers` issues a JWT for this email — whitelist it so CurrentUser-protected
    # routes accept it, matching a real logged-in (allowed) user.
    allowed = AllowedUser(email=_TEST_EMAIL, is_active=True, is_blocked=False)
    test_container.user_repo().seed(allowed)

    return TestClient(create_app())


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {encode_token(_TEST_EMAIL)}"}

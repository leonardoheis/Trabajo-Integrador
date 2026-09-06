from collections.abc import Callable
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from classiflow.api.app import create_app
from classiflow.api.dependencies import (
    get_audit_repo,
    get_classification_record_repo,
    get_document_kb_repo,
    get_document_steps_repo,
    get_enriched_record_repo,
    get_human_decision_repo,
    get_job_repo,
    get_job_service,
    get_pipeline_service,
    get_user_repo,
)
from classiflow.database.models import AllowedUser
from classiflow.injections.production import Container
from classiflow.injections.test import TestContainer
from classiflow.services.auth import encode_token

_TEST_EMAIL = "test@classiflow.dev"
_ADMIN_EMAIL = "admin@classiflow.dev"


# `Provide[Container.x]` markers throughout the app reference the *production* Container
# class by identity, so wiring a same-named but unrelated TestContainer instance can't
# satisfy them -- see the `client` fixture's own comment on that. The dependencies below
# are instead built from a native FastAPI Depends(get_session) in production, so
# container.override() there can't reach them either; they're swapped via FastAPI's own
# dependency_overrides mechanism, each pointed at a TestContainer provider. Every override
# must be a real, introspectable zero-arg function rather than the provider object itself:
# FastAPI's dependency_overrides calls inspect.signature() on the override callable to
# resolve its own sub-dependencies, and dependency_injector's Factory/Singleton provider
# instances are Cython-compiled callables that aren't introspectable that way, raising
# "ValueError: callable <dependency_injector.providers.Factory...> is not supported by
# signature" if passed directly.
def _test_override(getter: Callable[[], object]) -> Callable[[], object]:
    def _resolve() -> object:
        return getter()

    return _resolve


@pytest.fixture(scope="module")
def test_container() -> TestContainer:
    return TestContainer()


@pytest.fixture(scope="module")
def client(test_container: TestContainer) -> TestClient:
    # `Provide[Container.x]` markers throughout the app reference the *production*
    # Container class by identity, so wiring a same-named but unrelated TestContainer
    # instance can't satisfy them (dependency_injector's wiring maps providers by name
    # within one declarative class, not across two independent classes). Overriding a
    # Container() instance with a fresh TestContainer() instance keeps the exact provider
    # objects the markers point at, while swapping in the in-memory implementations.
    container = Container()
    container.override(test_container)
    container.wire(packages=["classiflow"])

    # `auth_headers` issues a JWT for this email — whitelist it so CurrentUser-protected
    # routes accept it, matching a real logged-in (allowed) user. created_at is set
    # explicitly since seed() bypasses create()'s own now()-stamping (server_default
    # only ever applies on a real SQL INSERT, which InMemoryUserRepository never does).
    now = datetime.now(timezone.utc)
    allowed = AllowedUser(
        email=_TEST_EMAIL, is_active=True, is_blocked=False, is_admin=False, created_at=now
    )
    test_container.user_repo().seed(allowed)

    admin = AllowedUser(
        email=_ADMIN_EMAIL, is_active=True, is_blocked=False, is_admin=True, created_at=now
    )
    test_container.user_repo().seed(admin)

    app = create_app()
    app.dependency_overrides.update({
        get_job_repo: _test_override(test_container.job_repo),
        get_document_steps_repo: _test_override(test_container.document_steps_repo),
        get_human_decision_repo: _test_override(test_container.human_decision_repo),
        get_classification_record_repo: _test_override(test_container.classification_record_repo),
        get_pipeline_service: _test_override(test_container.pipeline_service),
        get_job_service: _test_override(test_container.job_service),
        get_audit_repo: _test_override(test_container.audit_repo),
        get_user_repo: _test_override(test_container.user_repo),
        get_enriched_record_repo: _test_override(test_container.enriched_record_repo),
        get_document_kb_repo: _test_override(test_container.document_kb_repo),
    })

    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {encode_token(_TEST_EMAIL)}"}


@pytest.fixture
def auth_token() -> str:
    # Bare token (no "Bearer " prefix, no header dict) for the one route that can't
    # use an Authorization header -- GET /pipeline/{job_id}/events, authenticated via
    # a ?token= query param since EventSource can't set custom headers.
    return encode_token(_TEST_EMAIL)


@pytest.fixture
def admin_auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {encode_token(_ADMIN_EMAIL)}"}

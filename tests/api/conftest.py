from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar

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
from classiflow.injections import configure_container
from classiflow.injections.test import TestContainer
from classiflow.services.auth import encode_token

_TEST_EMAIL = "test@classiflow.dev"
_ADMIN_EMAIL = "admin@classiflow.dev"

_T = TypeVar("_T")


# FastAPI's dependency_overrides introspects the override callable's signature
# (inspect.signature()) to resolve its own sub-dependencies, and dependency_injector's
# Factory/Singleton provider instances are Cython-compiled callables that aren't
# introspectable that way -- passing one directly raises "ValueError: callable
# <dependency_injector.providers.Factory...> is not supported by signature". Wrapping
# each provider in a plain Python zero-arg function satisfies that requirement.
def _override(provider: Callable[[], _T]) -> Callable[[], _T]:
    def _get() -> _T:
        return provider()

    return _get


@pytest.fixture(scope="module")
def test_container() -> TestContainer:
    return TestContainer()


@pytest.fixture(scope="module")
def client(test_container: TestContainer) -> TestClient:
    # configure_container() (not a fresh Container()) so this reuses the exact same,
    # @cache-d singleton instance create_app() below also fetches -- create_app() calls
    # configure_container() itself now (see its own comment), and since that's cached,
    # its call is a no-op that returns this same, already-overridden-and-wired instance.
    # Building a second, competing Container() here would risk create_app()'s internal
    # configure_container() call re-wiring the real (non-test) providers on top of this
    # override, depending on call order.
    container = configure_container()
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

    # job_repo/document_steps_repo/human_decision_repo/pipeline_service are built from
    # a native FastAPI Depends(get_session) in production (see api/dependencies.py),
    # not from the dependency_injector Container -- container.override() above can't
    # reach them, so they're swapped via FastAPI's own override mechanism instead,
    # pointing straight at TestContainer's already-in-memory providers (see _override).
    app = create_app()
    app.dependency_overrides[get_job_repo] = _override(test_container.job_repo)
    app.dependency_overrides[get_document_steps_repo] = _override(
        test_container.document_steps_repo
    )
    app.dependency_overrides[get_human_decision_repo] = _override(
        test_container.human_decision_repo
    )
    app.dependency_overrides[get_classification_record_repo] = _override(
        test_container.classification_record_repo
    )
    app.dependency_overrides[get_pipeline_service] = _override(test_container.pipeline_service)
    app.dependency_overrides[get_job_service] = _override(test_container.job_service)
    app.dependency_overrides[get_audit_repo] = _override(test_container.audit_repo)
    app.dependency_overrides[get_user_repo] = _override(test_container.user_repo)
    app.dependency_overrides[get_enriched_record_repo] = _override(
        test_container.enriched_record_repo
    )
    app.dependency_overrides[get_document_kb_repo] = _override(test_container.document_kb_repo)

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

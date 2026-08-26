from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from classiflow.api.app import create_app
from classiflow.api.dependencies import (
    get_audit_repo,
    get_classification_record_repo,
    get_document_steps_repo,
    get_enriched_record_repo,
    get_human_decision_repo,
    get_job_repo,
    get_job_service,
    get_pipeline_service,
    get_user_repo,
)
from classiflow.database.models import AllowedUser
from classiflow.domain.repositories import (
    IClassificationRecordRepository,
    IDocumentStepsRepository,
    IEnrichedRecordRepository,
    IHumanDecisionRepository,
    IJobRepository,
    IUserRepository,
)
from classiflow.injections.production import Container
from classiflow.injections.test import TestContainer
from classiflow.services.audit.repository import IAuditRepository
from classiflow.services.auth import encode_token
from classiflow.services.job.service import JobService
from classiflow.services.pipeline.service import PipelineService

_TEST_EMAIL = "test@classiflow.dev"
_ADMIN_EMAIL = "admin@classiflow.dev"


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

    # job_repo/document_steps_repo/human_decision_repo/pipeline_service are built from
    # a native FastAPI Depends(get_session) in production (see api/dependencies.py),
    # not from the dependency_injector Container -- container.override() above can't
    # reach them, so they're swapped via FastAPI's own override mechanism instead,
    # pointing straight at TestContainer's already-in-memory providers. Plain functions
    # rather than the provider objects themselves: FastAPI's dependency_overrides
    # introspects the override callable's signature (inspect.signature()) to resolve
    # its own sub-dependencies, and dependency_injector's Factory/Singleton provider
    # instances are Cython-compiled callables that aren't introspectable that way --
    # passing one directly raises "ValueError: callable <dependency_injector.providers.
    # Factory...> is not supported by signature".
    def _job_repo_override() -> IJobRepository:
        return test_container.job_repo()

    def _document_steps_repo_override() -> IDocumentStepsRepository:
        return test_container.document_steps_repo()

    def _human_decision_repo_override() -> IHumanDecisionRepository:
        return test_container.human_decision_repo()

    def _classification_record_repo_override() -> IClassificationRecordRepository:
        return test_container.classification_record_repo()

    def _pipeline_service_override() -> PipelineService:
        return test_container.pipeline_service()

    def _job_service_override() -> JobService:
        return test_container.job_service()

    def _audit_repo_override() -> IAuditRepository:
        return test_container.audit_repo()

    def _user_repo_override() -> IUserRepository:
        return test_container.user_repo()

    def _enriched_record_repo_override() -> IEnrichedRecordRepository:
        return test_container.enriched_record_repo()

    app = create_app()
    app.dependency_overrides[get_job_repo] = _job_repo_override
    app.dependency_overrides[get_document_steps_repo] = _document_steps_repo_override
    app.dependency_overrides[get_human_decision_repo] = _human_decision_repo_override
    app.dependency_overrides[get_classification_record_repo] = _classification_record_repo_override
    app.dependency_overrides[get_pipeline_service] = _pipeline_service_override
    app.dependency_overrides[get_job_service] = _job_service_override
    app.dependency_overrides[get_audit_repo] = _audit_repo_override
    app.dependency_overrides[get_user_repo] = _user_repo_override
    app.dependency_overrides[get_enriched_record_repo] = _enriched_record_repo_override

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

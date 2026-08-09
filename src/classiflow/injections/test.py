from dependency_injector import containers, providers

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.database.repositories.document_steps import InMemoryDocumentStepsRepository
from classiflow.database.repositories.hash import InMemoryHashRepository
from classiflow.database.repositories.human_decision import InMemoryHumanDecisionRepository
from classiflow.database.repositories.job import InMemoryJobRepository
from classiflow.database.repositories.user import InMemoryUserRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.services.audit.service import AuditService
from classiflow.services.auth.service import AuthService


class TestContainer(containers.DeclarativeContainer):
    hash_repo = providers.Factory(InMemoryHashRepository)
    audit_repo = providers.Factory(InMemoryAuditRepository)
    # ponytail: Singleton so tests can seed the repo and the wired @inject sees the same instance
    user_repo = providers.Singleton(InMemoryUserRepository)
    document_steps_repo = providers.Factory(InMemoryDocumentStepsRepository)
    human_decision_repo = providers.Factory(InMemoryHumanDecisionRepository)
    job_repo = providers.Factory(InMemoryJobRepository)

    audit_service = providers.Factory(AuditService, repo=audit_repo)
    auth_service = providers.Factory(AuthService, user_repo=user_repo)
    broadcaster = providers.Singleton(EventBroadcaster)

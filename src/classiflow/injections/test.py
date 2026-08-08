from dependency_injector import containers, providers

from classiflow.shared.audit.service import AuditService
from classiflow.shared.database.repositories.audit import InMemoryAuditRepository
from classiflow.shared.database.repositories.document_steps import InMemoryDocumentStepsRepository
from classiflow.shared.database.repositories.hash import InMemoryHashRepository
from classiflow.shared.database.repositories.human_decision import InMemoryHumanDecisionRepository
from classiflow.shared.database.repositories.job import InMemoryJobRepository
from classiflow.shared.database.repositories.user import InMemoryUserRepository
from classiflow.shared.events.broadcaster import EventBroadcaster


class TestContainer(containers.DeclarativeContainer):
    hash_repo = providers.Factory(InMemoryHashRepository)
    audit_repo = providers.Factory(InMemoryAuditRepository)
    user_repo = providers.Factory(InMemoryUserRepository)
    document_steps_repo = providers.Factory(InMemoryDocumentStepsRepository)
    human_decision_repo = providers.Factory(InMemoryHumanDecisionRepository)
    job_repo = providers.Factory(InMemoryJobRepository)

    audit_service = providers.Factory(AuditService, repo=audit_repo)
    broadcaster = providers.Singleton(EventBroadcaster)

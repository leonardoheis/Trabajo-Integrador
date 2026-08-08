from dependency_injector import containers, providers

from classiflow.shared.audit.service import AuditService
from classiflow.shared.database.base import get_session
from classiflow.shared.database.repositories.audit import SqlAuditRepository
from classiflow.shared.database.repositories.document_steps import SqlDocumentStepsRepository
from classiflow.shared.database.repositories.hash import SqlHashRepository
from classiflow.shared.database.repositories.human_decision import SqlHumanDecisionRepository
from classiflow.shared.database.repositories.job import SqlJobRepository
from classiflow.shared.database.repositories.user import SqlUserRepository
from classiflow.shared.events.broadcaster import EventBroadcaster


class Container(containers.DeclarativeContainer):
    db_session = providers.Resource(get_session)

    hash_repo = providers.Factory(SqlHashRepository, session=db_session)
    audit_repo = providers.Factory(SqlAuditRepository, session=db_session)
    user_repo = providers.Factory(SqlUserRepository, session=db_session)
    document_steps_repo = providers.Factory(SqlDocumentStepsRepository, session=db_session)
    human_decision_repo = providers.Factory(SqlHumanDecisionRepository, session=db_session)
    job_repo = providers.Factory(SqlJobRepository, session=db_session)

    audit_service = providers.Factory(AuditService, repo=audit_repo)
    broadcaster = providers.Singleton(EventBroadcaster)

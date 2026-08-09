from functools import cache

from dependency_injector import containers, providers

from classiflow.database.base import get_session
from classiflow.database.repositories.audit import SqlAuditRepository
from classiflow.database.repositories.document_steps import SqlDocumentStepsRepository
from classiflow.database.repositories.hash import SqlHashRepository
from classiflow.database.repositories.human_decision import SqlHumanDecisionRepository
from classiflow.database.repositories.job import SqlJobRepository
from classiflow.database.repositories.user import SqlUserRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.services.audit.service import AuditService
from classiflow.services.auth.service import AuthService


class Container(containers.DeclarativeContainer):
    db_session = providers.Resource(get_session)

    hash_repo = providers.Factory(SqlHashRepository, session=db_session)
    audit_repo = providers.Factory(SqlAuditRepository, session=db_session)
    user_repo = providers.Factory(SqlUserRepository, session=db_session)
    document_steps_repo = providers.Factory(SqlDocumentStepsRepository, session=db_session)
    human_decision_repo = providers.Factory(SqlHumanDecisionRepository, session=db_session)
    job_repo = providers.Factory(SqlJobRepository, session=db_session)

    audit_service = providers.Factory(AuditService, repo=audit_repo)
    auth_service = providers.Factory(AuthService, user_repo=user_repo)
    broadcaster = providers.Singleton(EventBroadcaster)


@cache
def configure_container() -> Container:
    container = Container()
    container.wire(packages=["classiflow"])
    return container

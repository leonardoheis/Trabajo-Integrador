import asyncio
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.database.base import get_session
from classiflow.database.repositories.audit import SqlAuditRepository
from classiflow.database.repositories.document_steps import SqlDocumentStepsRepository
from classiflow.database.repositories.hash import IHashRepository, SqlHashRepository
from classiflow.database.repositories.human_decision import SqlHumanDecisionRepository
from classiflow.database.repositories.job import SqlJobRepository
from classiflow.domain.repositories.document_steps import IDocumentStepsRepository
from classiflow.domain.repositories.human_decision import IHumanDecisionRepository
from classiflow.domain.repositories.job import IJobRepository
from classiflow.domain.user import User
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.coordinator import build_coordinator
from classiflow.ingesta.extract import TextExtractFn
from classiflow.ingesta.nodes.extraction_step import ExtractionStep
from classiflow.ingesta.nodes.node1_file_reception import FileReceptionNode
from classiflow.ingesta.nodes.node2_format_validation import FormatValidationNode
from classiflow.ingesta.nodes.node3_content_validation import ContentValidationNode
from classiflow.ingesta.nodes.node4_duplicate_control import DuplicateControlNode
from classiflow.injections.production import Container
from classiflow.services.audit.service import AuditService
from classiflow.services.auth.service import AuthService
from classiflow.services.pipeline.service import PipelineService

_bearer = HTTPBearer()


@inject
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    auth_service: Annotated[AuthService, Depends(Provide[Container.auth_service])],
) -> User:
    return await auth_service.verify_token(credentials.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]

# Session-scoped repos/services, built fresh per request from FastAPI's own native
# yield-dependency (not dependency_injector's Resource, which has no per-request
# teardown hook -- see injections/production.py's Container docstring comment for why).
DbSession = Annotated[AsyncSession, Depends(get_session)]


def get_job_repo(session: DbSession) -> IJobRepository:
    return SqlJobRepository(session)


def get_document_steps_repo(session: DbSession) -> IDocumentStepsRepository:
    return SqlDocumentStepsRepository(session)


def get_human_decision_repo(session: DbSession) -> IHumanDecisionRepository:
    return SqlHumanDecisionRepository(session)


def get_hash_repo(session: DbSession) -> IHashRepository:
    return SqlHashRepository(session)


def get_audit_service(session: DbSession) -> AuditService:
    return AuditService(SqlAuditRepository(session))


@inject
def get_coordinator(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    hash_repo: Annotated[IHashRepository, Depends(get_hash_repo)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    text_extractor: Annotated[TextExtractFn, Depends(Provide[Container.text_extractor])],
    extraction_semaphore: Annotated[
        asyncio.Semaphore, Depends(Provide[Container.extraction_semaphore])
    ],
) -> CompiledStateGraph:  # type: ignore[type-arg]
    node1 = FileReceptionNode(audit=audit_service, broadcaster=broadcaster)
    node2 = FormatValidationNode(audit=audit_service, broadcaster=broadcaster)
    node3 = ContentValidationNode(audit=audit_service, broadcaster=broadcaster)
    node4 = DuplicateControlNode(audit=audit_service, broadcaster=broadcaster, hash_repo=hash_repo)
    extraction_step = ExtractionStep(
        audit=audit_service,
        broadcaster=broadcaster,
        text_extractor=text_extractor,
        semaphore=extraction_semaphore,
    )
    return build_coordinator(node1, node2, node3, node4, extraction_step=extraction_step)


@inject
def get_pipeline_service(
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    document_steps_repo: Annotated[IDocumentStepsRepository, Depends(get_document_steps_repo)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    coordinator: Annotated[CompiledStateGraph, Depends(get_coordinator)],  # type: ignore[type-arg]
) -> PipelineService:
    return PipelineService(
        job_repo=job_repo,
        document_steps_repo=document_steps_repo,
        broadcaster=broadcaster,
        coordinator=coordinator,
    )

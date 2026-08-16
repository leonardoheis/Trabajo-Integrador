from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.database.base import get_session
from classiflow.database.repositories.audit import SqlAuditRepository
from classiflow.database.repositories.document import SqlDocumentRepository
from classiflow.database.repositories.document_steps import SqlDocumentStepsRepository
from classiflow.database.repositories.hash import IHashRepository, SqlHashRepository
from classiflow.database.repositories.human_decision import SqlHumanDecisionRepository
from classiflow.database.repositories.job import SqlJobRepository
from classiflow.domain.repositories.document import IDocumentRepository
from classiflow.domain.repositories.document_steps import IDocumentStepsRepository
from classiflow.domain.repositories.human_decision import IHumanDecisionRepository
from classiflow.domain.repositories.job import IJobRepository
from classiflow.domain.user import User
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.coordinator import TextExtractFn, build_coordinator
from classiflow.ingesta.nodes.node1_file_reception import FileReceptionNode
from classiflow.ingesta.nodes.node2_format_validation import FormatValidationNode
from classiflow.ingesta.nodes.node3_content_validation import ContentValidationNode
from classiflow.ingesta.nodes.node4_duplicate_control import DuplicateControlNode
from classiflow.ingesta.nodes.node5_knowledge_indexing import KnowledgeIndexingNode
from classiflow.injections.production import Container
from classiflow.knowledge.chunker import ChunkerService
from classiflow.knowledge.indexer import IndexerService
from classiflow.knowledge.rag import RagService
from classiflow.knowledge.repositories.chat_llm import IChatLlm
from classiflow.knowledge.repositories.document_metadata import IDocumentMetadataRepository
from classiflow.knowledge.repositories.embedder import IEmbedder
from classiflow.knowledge.repositories.vector_store import IVectorStore
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


def get_document_repo(session: DbSession) -> IDocumentRepository:
    return SqlDocumentRepository(session)


def get_audit_service(session: DbSession) -> AuditService:
    return AuditService(SqlAuditRepository(session))


@inject
def get_indexer(
    chunker: Annotated[ChunkerService, Depends(Provide[Container.chunker])],
    embedder: Annotated[IEmbedder, Depends(Provide[Container.embedder])],
    vector_store: Annotated[IVectorStore, Depends(Provide[Container.vector_store])],
    metadata_repo: Annotated[
        IDocumentMetadataRepository, Depends(Provide[Container.document_metadata_repo])
    ],
) -> IndexerService:
    return IndexerService(
        chunker=chunker,
        embedder=embedder,
        vector_store=vector_store,
        metadata_repo=metadata_repo,
    )


@inject
def get_rag_service(
    embedder: Annotated[IEmbedder, Depends(Provide[Container.embedder])],
    vector_store: Annotated[IVectorStore, Depends(Provide[Container.vector_store])],
    chat_llm: Annotated[IChatLlm, Depends(Provide[Container.chat_llm])],
) -> RagService:
    return RagService(embedder=embedder, vector_store=vector_store, chat_llm=chat_llm)


# Each kwarg is an independently-injected collaborator; bundling them into a params
# object would only obscure the wiring.
@inject
def get_coordinator(  # noqa: PLR0913, PLR0917
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    hash_repo: Annotated[IHashRepository, Depends(get_hash_repo)],
    document_repo: Annotated[IDocumentRepository, Depends(get_document_repo)],
    indexer: Annotated[IndexerService, Depends(get_indexer)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    text_extractor: Annotated[TextExtractFn, Depends(Provide[Container.text_extractor])],
) -> CompiledStateGraph:  # type: ignore[type-arg]
    node1 = FileReceptionNode(audit=audit_service, broadcaster=broadcaster)
    node2 = FormatValidationNode(audit=audit_service, broadcaster=broadcaster)
    node3 = ContentValidationNode(audit=audit_service, broadcaster=broadcaster)
    node4 = DuplicateControlNode(audit=audit_service, broadcaster=broadcaster, hash_repo=hash_repo)
    node5 = KnowledgeIndexingNode(
        audit=audit_service,
        broadcaster=broadcaster,
        indexer=indexer,
        document_repo=document_repo,
    )
    return build_coordinator(node1, node2, node3, node4, node5, text_extractor=text_extractor)


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

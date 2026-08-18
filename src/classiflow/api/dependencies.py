import asyncio
from typing import TYPE_CHECKING, Annotated, cast

from dependency_injector.wiring import Provide, inject
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.runnables import Runnable
from langgraph.graph.state import CompiledStateGraph
from lingua import LanguageDetector
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.database.base import get_session
from classiflow.database.repositories.audit import SqlAuditRepository
from classiflow.database.repositories.document_steps import SqlDocumentStepsRepository
from classiflow.database.repositories.enriched_record import SqlEnrichedRecordRepository
from classiflow.database.repositories.hash import IHashRepository, SqlHashRepository
from classiflow.database.repositories.human_decision import SqlHumanDecisionRepository
from classiflow.database.repositories.job import SqlJobRepository
from classiflow.domain.repositories.document_steps import IDocumentStepsRepository
from classiflow.domain.repositories.enriched_record import IEnrichedRecordRepository
from classiflow.domain.repositories.human_decision import IHumanDecisionRepository
from classiflow.domain.repositories.job import IJobRepository
from classiflow.domain.user import User
from classiflow.enrichment.coordinator import build_enrichment_coordinator
from classiflow.enrichment.nodes import EntityExtractorNode, MetadataEnricherNode, TextCleanerNode
from classiflow.enrichment.prompts.entity_extraction import (
    EntityExtractionInput,
    EntityExtractionOutput,
)
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.coordinator import build_coordinator
from classiflow.ingesta.extract import TextExtractFn
from classiflow.ingesta.nodes import (
    ContentValidationNode,
    DuplicateControlNode,
    ExtractionStep,
    FileReceptionNode,
    FormatValidationNode,
)
from classiflow.ingesta.nodes.node4_duplicate_control import EmbeddingStore
from classiflow.ingesta.prompts import (
    ContentChainInput,
    FormatChainInput,
    FormatDecisionOutput,
    LegitimacyDecisionOutput,
)
from classiflow.injections.production import Container
from classiflow.services.audit.service import AuditService
from classiflow.services.auth.service import AuthService
from classiflow.services.pipeline.service import PipelineService
from classiflow.storage.document_storage import IDocumentStorage

if TYPE_CHECKING:
    from classiflow.enrichment.nodes.entity_extractor import _EntityChain
    from classiflow.ingesta.nodes.node2_format_validation import _FormatChain
    from classiflow.ingesta.nodes.node3_content_validation import _ContentChain

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
def get_node1(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> FileReceptionNode:
    return FileReceptionNode(audit=audit_service, broadcaster=broadcaster)


@inject
def get_node2(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    format_chain: Annotated[
        Runnable[FormatChainInput, FormatDecisionOutput],
        Depends(Provide[Container.node2_format_chain]),
    ],
) -> FormatValidationNode:
    return FormatValidationNode(
        audit=audit_service,
        broadcaster=broadcaster,
        format_chain=cast("_FormatChain", format_chain),
    )


@inject
def get_node3(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    language_detector: Annotated[LanguageDetector, Depends(Provide[Container.language_detector])],
    content_chain: Annotated[
        Runnable[ContentChainInput, LegitimacyDecisionOutput],
        Depends(Provide[Container.node3_content_chain]),
    ],
) -> ContentValidationNode:
    return ContentValidationNode(
        audit=audit_service,
        broadcaster=broadcaster,
        language_detector=language_detector,
        content_chain=cast("_ContentChain", content_chain),
    )


@inject
def get_node4(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    hash_repo: Annotated[IHashRepository, Depends(get_hash_repo)],
    embedding_store: Annotated[EmbeddingStore, Depends(Provide[Container.embedding_store])],
) -> DuplicateControlNode:
    return DuplicateControlNode(
        audit=audit_service,
        broadcaster=broadcaster,
        hash_repo=hash_repo,
        embedding_store=embedding_store,
    )


def get_enriched_record_repo(session: DbSession) -> IEnrichedRecordRepository:
    return SqlEnrichedRecordRepository(session)


@inject
def get_text_cleaner(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> TextCleanerNode:
    return TextCleanerNode(audit=audit_service, broadcaster=broadcaster)


@inject
def get_entity_extractor(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    entity_chain: Annotated[
        Runnable[EntityExtractionInput, EntityExtractionOutput],
        Depends(Provide[Container.entity_extraction_chain]),
    ],
) -> EntityExtractorNode:
    return EntityExtractorNode(
        audit=audit_service,
        broadcaster=broadcaster,
        entity_chain=cast("_EntityChain", entity_chain),
    )


@inject
def get_metadata_enricher(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> MetadataEnricherNode:
    return MetadataEnricherNode(audit=audit_service, broadcaster=broadcaster)


def get_enrichment_coordinator(
    text_cleaner: Annotated[TextCleanerNode, Depends(get_text_cleaner)],
    entity_extractor: Annotated[EntityExtractorNode, Depends(get_entity_extractor)],
    metadata_enricher: Annotated[MetadataEnricherNode, Depends(get_metadata_enricher)],
) -> CompiledStateGraph:  # type: ignore[type-arg]
    return build_enrichment_coordinator(text_cleaner, entity_extractor, metadata_enricher)


@inject
def get_extraction_step(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    text_extractor: Annotated[TextExtractFn, Depends(Provide[Container.text_extractor])],
    extraction_semaphore: Annotated[
        asyncio.Semaphore, Depends(Provide[Container.extraction_semaphore])
    ],
) -> ExtractionStep:
    return ExtractionStep(
        audit=audit_service,
        broadcaster=broadcaster,
        text_extractor=text_extractor,
        semaphore=extraction_semaphore,
    )


@inject
def get_coordinator(
    node1: Annotated[FileReceptionNode, Depends(get_node1)],
    node2: Annotated[FormatValidationNode, Depends(get_node2)],
    node3: Annotated[ContentValidationNode, Depends(get_node3)],
    node4: Annotated[DuplicateControlNode, Depends(get_node4)],
    extraction_step: Annotated[ExtractionStep, Depends(get_extraction_step)],
) -> CompiledStateGraph:  # type: ignore[type-arg]
    return build_coordinator(node1, node2, node3, node4, extraction_step=extraction_step)


@inject
def get_pipeline_service(
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    document_steps_repo: Annotated[IDocumentStepsRepository, Depends(get_document_steps_repo)],
    enriched_record_repo: Annotated[IEnrichedRecordRepository, Depends(get_enriched_record_repo)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    coordinator: Annotated[CompiledStateGraph, Depends(get_coordinator)],  # type: ignore[type-arg]
    enrichment_coordinator: Annotated[  # type: ignore[type-arg]
        CompiledStateGraph, Depends(get_enrichment_coordinator)
    ],
    document_storage: Annotated[IDocumentStorage, Depends(Provide[Container.document_storage])],
) -> PipelineService:
    return PipelineService(
        job_repo=job_repo,
        document_steps_repo=document_steps_repo,
        enriched_record_repo=enriched_record_repo,
        broadcaster=broadcaster,
        coordinator=coordinator,
        enrichment_coordinator=enrichment_coordinator,
        document_storage=document_storage,
    )

import asyncio
from http import HTTPStatus
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.graph.state import CompiledStateGraph
from lingua import LanguageDetector
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.classification.coordinator import build_classification_coordinator
from classiflow.classification.nodes import (
    ConfidenceGateNode,
    ForeignMunicipalityNode,
    LlmJudgeNode,
    PrimaryClassifierNode,
    RoutingNode,
    SecondOpinionNode,
    SmellsRiskNode,
)
from classiflow.database.base import get_session
from classiflow.database.repositories.audit import SqlAuditRepository
from classiflow.database.repositories.classification_record import (
    SqlClassificationRecordRepository,
)
from classiflow.database.repositories.document_steps import SqlDocumentStepsRepository
from classiflow.database.repositories.enriched_record import SqlEnrichedRecordRepository
from classiflow.database.repositories.hash import IHashRepository, SqlHashRepository
from classiflow.database.repositories.human_decision import SqlHumanDecisionRepository
from classiflow.database.repositories.job import SqlJobRepository
from classiflow.database.repositories.user import SqlUserRepository
from classiflow.domain.repositories.classification_record import IClassificationRecordRepository
from classiflow.domain.repositories.document_steps import IDocumentStepsRepository
from classiflow.domain.repositories.enriched_record import IEnrichedRecordRepository
from classiflow.domain.repositories.human_decision import IHumanDecisionRepository
from classiflow.domain.repositories.job import IJobRepository
from classiflow.domain.repositories.user import IUserRepository
from classiflow.domain.user import User
from classiflow.enrichment.coordinator import build_enrichment_coordinator
from classiflow.enrichment.nodes import EntityExtractorNode, MetadataEnricherNode, TextCleanerNode
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
from classiflow.injections.production import Container
from classiflow.services.audit.repository import IAuditRepository
from classiflow.services.audit.service import AuditService
from classiflow.services.auth.service import AuthService
from classiflow.services.job.service import JobService
from classiflow.services.pipeline.service import PipelineService
from classiflow.storage.document_storage import IDocumentStorage

_bearer = HTTPBearer()


@inject
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    auth_service: Annotated[AuthService, Depends(Provide[Container.auth_service])],
) -> User:
    return await auth_service.verify_token(credentials.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]


# EventSource (the browser API backing GET /pipeline/{job_id}/events) cannot set
# custom request headers -- there is no way to attach Authorization: Bearer <token>
# to it, so this is the standard SSE-specific fallback: accept the token from a query
# param instead. Used only for that one streaming route; every other route keeps
# requiring a real Authorization header via CurrentUser/get_current_user above.
@inject
async def get_current_user_from_query_token(
    token: str,
    auth_service: Annotated[AuthService, Depends(Provide[Container.auth_service])],
) -> User:
    return await auth_service.verify_token(token)


CurrentUserFromQueryToken = Annotated[User, Depends(get_current_user_from_query_token)]


def require_admin(current_user: CurrentUser) -> None:
    if not current_user.is_admin:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Admin access required")


# Session-scoped repos/services, built fresh per request from FastAPI's own native
# yield-dependency (not dependency_injector's Resource, which has no per-request
# teardown hook -- see injections/production.py's Container docstring comment for why).
DbSession = Annotated[AsyncSession, Depends(get_session)]


def get_job_repo(session: DbSession) -> IJobRepository:
    return SqlJobRepository(session)


def get_user_repo(session: DbSession) -> IUserRepository:
    return SqlUserRepository(session)


def get_document_steps_repo(session: DbSession) -> IDocumentStepsRepository:
    return SqlDocumentStepsRepository(session)


def get_human_decision_repo(session: DbSession) -> IHumanDecisionRepository:
    return SqlHumanDecisionRepository(session)


def get_job_service(
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    document_steps_repo: Annotated[IDocumentStepsRepository, Depends(get_document_steps_repo)],
    human_decision_repo: Annotated[IHumanDecisionRepository, Depends(get_human_decision_repo)],
) -> JobService:
    return JobService(job_repo, document_steps_repo, human_decision_repo)


def get_hash_repo(session: DbSession) -> IHashRepository:
    return SqlHashRepository(session)


def get_audit_repo(session: DbSession) -> IAuditRepository:
    return SqlAuditRepository(session)


def get_audit_service(session: DbSession) -> AuditService:
    return AuditService(SqlAuditRepository(session))


@inject
def get_node1(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> FileReceptionNode:
    return FileReceptionNode(audit=audit_service, broadcaster=broadcaster)


# The *_chain dependencies below are deliberately NOT injected. FastAPI resolves every
# dependency of a route before the handler runs, so injecting them would build their
# GGUF models at request time and keep them referenced by the container for the process
# lifetime -- unload_slm() could then never free that VRAM, and each job would start
# with whatever the previous one left behind (measured: 1.92GB free instead of 6.96GB,
# forcing llama.cpp to offload most layers to CPU). Each node already builds its chain
# on demand when left as None, so only one model is resident at a time.
@inject
def get_node2(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> FormatValidationNode:
    return FormatValidationNode(audit=audit_service, broadcaster=broadcaster)


@inject
def get_node3(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    language_detector: Annotated[LanguageDetector, Depends(Provide[Container.language_detector])],
) -> ContentValidationNode:
    return ContentValidationNode(
        audit=audit_service,
        broadcaster=broadcaster,
        language_detector=language_detector,
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
) -> EntityExtractorNode:
    return EntityExtractorNode(audit=audit_service, broadcaster=broadcaster)


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


def get_classification_record_repo(session: DbSession) -> IClassificationRecordRepository:
    return SqlClassificationRecordRepository(session)


@inject
def get_primary_classifier(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> PrimaryClassifierNode:
    return PrimaryClassifierNode(audit=audit_service, broadcaster=broadcaster)


@inject
def get_second_opinion(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> SecondOpinionNode:
    return SecondOpinionNode(audit=audit_service, broadcaster=broadcaster)


@inject
def get_foreign_municipality(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> ForeignMunicipalityNode:
    return ForeignMunicipalityNode(audit=audit_service, broadcaster=broadcaster)


@inject
def get_smells_risk(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> SmellsRiskNode:
    return SmellsRiskNode(audit=audit_service, broadcaster=broadcaster)


@inject
def get_confidence_gate(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> ConfidenceGateNode:
    return ConfidenceGateNode(audit=audit_service, broadcaster=broadcaster)


@inject
def get_llm_judge(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> LlmJudgeNode:
    # judge_chain is deliberately NOT injected. FastAPI resolves every dependency of a
    # route before the handler runs, so injecting it would build the judge's GGUF at
    # request time -- resident alongside the node2/node3/classification model and
    # exhausting an 8GB card before any document is processed, which then makes the
    # next job's model load fail. Left as None, LlmJudgeNode builds the chain on demand
    # and calls unload_slm() first, so only one model is ever resident.
    return LlmJudgeNode(audit=audit_service, broadcaster=broadcaster)


@inject
def get_routing(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
    document_storage: Annotated[IDocumentStorage, Depends(Provide[Container.document_storage])],
    classification_record_repo: Annotated[
        IClassificationRecordRepository, Depends(get_classification_record_repo)
    ],
) -> RoutingNode:
    return RoutingNode(
        audit=audit_service,
        broadcaster=broadcaster,
        storage=document_storage,
        classification_repo=classification_record_repo,
    )


def get_classification_coordinator(
    primary_classifier: Annotated[PrimaryClassifierNode, Depends(get_primary_classifier)],
    second_opinion: Annotated[SecondOpinionNode, Depends(get_second_opinion)],
    foreign_municipality: Annotated[ForeignMunicipalityNode, Depends(get_foreign_municipality)],
    smells_risk: Annotated[SmellsRiskNode, Depends(get_smells_risk)],
    confidence_gate: Annotated[ConfidenceGateNode, Depends(get_confidence_gate)],
    llm_judge: Annotated[LlmJudgeNode, Depends(get_llm_judge)],
    routing: Annotated[RoutingNode, Depends(get_routing)],
) -> CompiledStateGraph:  # type: ignore[type-arg]
    return build_classification_coordinator(
        primary_classifier,
        second_opinion,
        foreign_municipality,
        smells_risk,
        confidence_gate,
        llm_judge,
        routing,
    )


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
    classification_coordinator: Annotated[  # type: ignore[type-arg]
        CompiledStateGraph, Depends(get_classification_coordinator)
    ],
    job_semaphore: Annotated[asyncio.Semaphore, Depends(Provide[Container.job_semaphore])],
) -> PipelineService:
    return PipelineService(
        job_repo=job_repo,
        document_steps_repo=document_steps_repo,
        enriched_record_repo=enriched_record_repo,
        broadcaster=broadcaster,
        coordinator=coordinator,
        enrichment_coordinator=enrichment_coordinator,
        document_storage=document_storage,
        classification_coordinator=classification_coordinator,
        job_semaphore=job_semaphore,
    )

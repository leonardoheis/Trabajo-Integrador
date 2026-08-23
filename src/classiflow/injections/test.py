import asyncio
import tempfile
from collections.abc import AsyncIterator

import numpy as np
import numpy.typing as npt
from dependency_injector import containers, providers
from langchain_core.runnables import Runnable

from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.coordinator import build_classification_coordinator
from classiflow.classification.domain.results import JudgeOutput, PrimaryClassificationOutput
from classiflow.classification.nodes import (
    ConfidenceGateNode,
    ForeignMunicipalityNode,
    LlmJudgeNode,
    PrimaryClassifierNode,
    RoutingNode,
    SecondOpinionNode,
    SmellsRiskNode,
)
from classiflow.classification.prompts.llm_judge import JudgeInput, build_judge_chain
from classiflow.classification.prompts.primary_classification import (
    PrimaryClassificationInput,
    build_classification_chain,
)
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.database.repositories.classification_record import (
    InMemoryClassificationRecordRepository,
)
from classiflow.database.repositories.document import InMemoryDocumentRepository
from classiflow.database.repositories.document_steps import InMemoryDocumentStepsRepository
from classiflow.database.repositories.enriched_record import InMemoryEnrichedRecordRepository
from classiflow.database.repositories.hash import InMemoryHashRepository
from classiflow.database.repositories.human_decision import InMemoryHumanDecisionRepository
from classiflow.database.repositories.job import InMemoryJobRepository
from classiflow.database.repositories.user import InMemoryUserRepository
from classiflow.enrichment.coordinator import build_enrichment_coordinator
from classiflow.enrichment.nodes import EntityExtractorNode, MetadataEnricherNode, TextCleanerNode
from classiflow.enrichment.prompts.entity_extraction import (
    EntityExtractionInput,
    EntityExtractionOutput,
    build_entity_extraction_chain,
)
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.coordinator import build_coordinator
from classiflow.ingesta.domain import ExtractionResult
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.ingesta.nodes import (
    ContentValidationNode,
    DuplicateControlNode,
    ExtractionStep,
    FileReceptionNode,
    FormatValidationNode,
    KnowledgeIndexingNode,
)
from classiflow.ingesta.nodes.node4_duplicate_control import EmbeddingStore
from classiflow.knowledge.chat.service import ChatService
from classiflow.knowledge.chunking.chunker import ChunkerService
from classiflow.knowledge.domain.document import DocumentMetadata
from classiflow.knowledge.indexing.indexer import IndexerService
from classiflow.knowledge.retrieval.retriever import RetrieverService
from classiflow.knowledge.vectordb.in_memory_store import InMemoryVectorStore
from classiflow.services.audit.service import AuditService
from classiflow.services.auth.service import AuthService
from classiflow.services.job.service import JobService
from classiflow.services.pipeline.service import PipelineService
from classiflow.storage.document_storage import LocalDiskStorage

# ponytail: fixed Spanish sample instead of real extraction — tests need deterministic,
# non-empty, allowed-language text to reach node3/node4, and shouldn't pay for real
# MarkItDown/OCR calls (or their model downloads) on every test run.
_TEST_TEXT = (
    "El Concejo Municipal de Rosario sanciona la siguiente ordenanza: "
    "Artículo 1º — Apruébase el presupuesto municipal para el ejercicio fiscal "
    "correspondiente al año en curso, conforme al detalle que se adjunta como Anexo I."
)


def _test_mime_detector(file_bytes: bytes) -> str:
    return "application/pdf" if file_bytes.startswith(b"%PDF") else "application/octet-stream"


def _test_embed(_text: str) -> npt.NDArray[np.float32]:
    return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


class _StubEmbedder:
    """Deterministic 3-d embedding: no model download, no inference in tests."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:  # noqa: PLR6301
        lowered = text.lower()
        return [
            1.0 if "ordenanza" in lowered else 0.0,
            1.0 if "presupuesto" in lowered else 0.0,
            float(len(lowered) % 3) / 3.0,
        ]


class _StubChatLlm:
    """Echoes a fixed Spanish answer, mirroring MockLlm's role for the SLM nodes.

    Duck-typed like the sibling stubs: subclassing ChatLlm would force the unused
    parameters to keep the base's names and trip ARG002.
    """

    def __init__(self, response: str = "Según los pasajes provistos, no hay datos.") -> None:
        self._response = response

    async def astream(self, _system: str, _user: str) -> AsyncIterator[str]:
        yield self._response


class _StubMetadataRepository:
    def resolve(self, filename: str) -> DocumentMetadata:  # noqa: PLR6301
        return DocumentMetadata(
            filename=filename,
            doc_type="Ordenanza",
            number="10902",
            year="2026",
            subject="Presupuesto municipal",
            download_url="https://www.rosario.gob.ar/normativa/ver/test",
        )


_TEST_ENTITY_RESPONSE = (
    '{"doc_type_hint": "ordenanza", "number": "1", "year": 2024, '
    '"issuing_body": "Concejo Municipal", "signatories": [], "article_count": 1}'
)


def _test_entity_chain() -> Runnable[EntityExtractionInput, EntityExtractionOutput]:
    return build_entity_extraction_chain(MockLlm(response=_TEST_ENTITY_RESPONSE))


_TEST_PRIMARY_RESPONSE = '{"label": "ordenanzas", "confidence": 0.95, "reasoning": "test"}'
_TEST_JUDGE_RESPONSE = '{"accept": true, "final_label": "ordenanzas", "reasoning": "test"}'
# ponytail: second_opinion disabled in tests -- avoids loading the real ~425MB BETO
# model (weights + OOD/SVM artifacts) on every test run. SecondOpinionNode already
# treats this as a normal, fully-supported config state (returns None).
_TEST_CLASSIFICATION_CONFIG = ClassificationConfig(second_opinion_enabled=False)


def _test_classification_chain() -> Runnable[
    PrimaryClassificationInput, PrimaryClassificationOutput
]:
    return build_classification_chain(MockLlm(response=_TEST_PRIMARY_RESPONSE))


def _test_judge_chain() -> Runnable[JudgeInput, JudgeOutput]:
    return build_judge_chain(MockLlm(response=_TEST_JUDGE_RESPONSE))


# ponytail: reuse the real LocalDiskStorage against a throwaway temp directory instead
# of inventing a fake in-memory storage class -- one less code path to diverge from
# production, and TestContainer is module-scoped so a pytest tmp_path fixture isn't
# available here.
_TEST_STORAGE_ROOT = tempfile.mkdtemp(prefix="classiflow-test-storage-")


class TestContainer(containers.DeclarativeContainer):
    hash_repo = providers.Factory(InMemoryHashRepository)
    audit_repo = providers.Factory(InMemoryAuditRepository)
    # ponytail: Singleton so state (seeded users, created jobs/steps/decisions) survives
    # across the multiple requests one test makes against the shared `client` fixture.
    user_repo = providers.Singleton(InMemoryUserRepository)
    document_steps_repo = providers.Singleton(InMemoryDocumentStepsRepository)
    human_decision_repo = providers.Singleton(InMemoryHumanDecisionRepository)
    job_repo = providers.Singleton(InMemoryJobRepository)
    enriched_record_repo = providers.Singleton(InMemoryEnrichedRecordRepository)
    document_storage = providers.Singleton(LocalDiskStorage, root=_TEST_STORAGE_ROOT)
    entity_extraction_chain = providers.Singleton(_test_entity_chain)
    classification_record_repo = providers.Singleton(InMemoryClassificationRecordRepository)
    classification_chain = providers.Singleton(_test_classification_chain)
    judge_chain = providers.Singleton(_test_judge_chain)

    audit_service = providers.Factory(AuditService, repo=audit_repo)
    auth_service = providers.Factory(AuthService, user_repo=user_repo)
    job_service = providers.Factory(
        JobService,
        job_repo=job_repo,
        document_steps_repo=document_steps_repo,
        human_decision_repo=human_decision_repo,
    )
    broadcaster = providers.Singleton(EventBroadcaster)

    text_extractor = providers.Object(
        lambda _b, _f: ExtractionResult(
            text=_TEST_TEXT, extractor_used="test", char_count=len(_TEST_TEXT)
        )
    )
    # Generous cap -- shouldn't gate tests, just needs to satisfy the now-required param.
    extraction_semaphore = providers.Singleton(asyncio.Semaphore, 100)
    job_semaphore = providers.Singleton(asyncio.Semaphore, 100)
    extraction_step = providers.Factory(
        ExtractionStep,
        audit=audit_service,
        broadcaster=broadcaster,
        text_extractor=text_extractor,
        semaphore=extraction_semaphore,
    )
    node1 = providers.Factory(
        FileReceptionNode,
        audit=audit_service,
        broadcaster=broadcaster,
        mime_detector=_test_mime_detector,
    )
    node2 = providers.Factory(FormatValidationNode, audit=audit_service, broadcaster=broadcaster)
    node3 = providers.Factory(ContentValidationNode, audit=audit_service, broadcaster=broadcaster)
    node4 = providers.Factory(
        DuplicateControlNode,
        audit=audit_service,
        broadcaster=broadcaster,
        hash_repo=hash_repo,
        embedding_store=providers.Factory(EmbeddingStore, dim=4, embed_fn=_test_embed),
    )
    document_repo = providers.Singleton(InMemoryDocumentRepository)
    vector_store = providers.Singleton(InMemoryVectorStore)
    embedder = providers.Singleton(_StubEmbedder)
    chat_llm = providers.Singleton(_StubChatLlm)
    chunker = providers.Factory(ChunkerService)
    document_metadata_repo = providers.Singleton(_StubMetadataRepository)
    indexer = providers.Factory(
        IndexerService,
        chunker=chunker,
        embedder=embedder,
        vector_store=vector_store,
        metadata_repo=document_metadata_repo,
    )
    retriever = providers.Factory(
        RetrieverService,
        embedder=embedder,
        vector_store=vector_store,
    )
    chat_service = providers.Factory(
        ChatService,
        retriever=retriever,
        chat_llm=chat_llm,
    )
    node5 = providers.Factory(
        KnowledgeIndexingNode,
        audit=audit_service,
        broadcaster=broadcaster,
        indexer=indexer,
        document_repo=document_repo,
    )

    enrichment_text_cleaner = providers.Factory(
        TextCleanerNode, audit=audit_service, broadcaster=broadcaster
    )
    enrichment_entity_extractor = providers.Factory(
        EntityExtractorNode,
        audit=audit_service,
        broadcaster=broadcaster,
        entity_chain=entity_extraction_chain,
    )
    enrichment_metadata_enricher = providers.Factory(
        MetadataEnricherNode, audit=audit_service, broadcaster=broadcaster
    )
    enrichment_coordinator = providers.Factory(
        build_enrichment_coordinator,
        text_cleaner=enrichment_text_cleaner,
        entity_extractor=enrichment_entity_extractor,
        metadata_enricher=enrichment_metadata_enricher,
    )
    classification_primary_classifier = providers.Factory(
        PrimaryClassifierNode,
        audit=audit_service,
        broadcaster=broadcaster,
        classification_chain=classification_chain,
        config=_TEST_CLASSIFICATION_CONFIG,
    )
    classification_second_opinion = providers.Factory(
        SecondOpinionNode,
        audit=audit_service,
        broadcaster=broadcaster,
        config=_TEST_CLASSIFICATION_CONFIG,
    )
    classification_foreign_municipality = providers.Factory(
        ForeignMunicipalityNode,
        audit=audit_service,
        broadcaster=broadcaster,
        config=_TEST_CLASSIFICATION_CONFIG,
    )
    classification_smells_risk = providers.Factory(
        SmellsRiskNode,
        audit=audit_service,
        broadcaster=broadcaster,
        config=_TEST_CLASSIFICATION_CONFIG,
    )
    classification_confidence_gate = providers.Factory(
        ConfidenceGateNode,
        audit=audit_service,
        broadcaster=broadcaster,
        config=_TEST_CLASSIFICATION_CONFIG,
    )
    classification_llm_judge = providers.Factory(
        LlmJudgeNode, audit=audit_service, broadcaster=broadcaster, judge_chain=judge_chain
    )
    classification_routing = providers.Factory(
        RoutingNode,
        audit=audit_service,
        broadcaster=broadcaster,
        storage=document_storage,
        classification_repo=classification_record_repo,
    )
    classification_coordinator = providers.Factory(
        build_classification_coordinator,
        primary_classifier=classification_primary_classifier,
        second_opinion=classification_second_opinion,
        foreign_municipality=classification_foreign_municipality,
        smells_risk=classification_smells_risk,
        confidence_gate=classification_confidence_gate,
        llm_judge=classification_llm_judge,
        routing=classification_routing,
    )
    coordinator = providers.Factory(
        build_coordinator,
        node1=node1,
        node2=node2,
        node3=node3,
        node4=node4,
        node5=node5,
        extraction_step=extraction_step,
    )
    pipeline_service = providers.Factory(
        PipelineService,
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

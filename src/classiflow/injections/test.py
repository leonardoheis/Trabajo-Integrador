import asyncio
import tempfile

import numpy as np
import numpy.typing as npt
from dependency_injector import containers, providers
from langchain_core.runnables import Runnable

from classiflow.database.repositories.audit import InMemoryAuditRepository
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
)
from classiflow.ingesta.nodes.node4_duplicate_control import EmbeddingStore
from classiflow.services.audit.service import AuditService
from classiflow.services.auth.service import AuthService
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


_TEST_ENTITY_RESPONSE = (
    '{"doc_type_hint": "ordenanza", "number": "1", "year": 2024, '
    '"issuing_body": "Concejo Municipal", "signatories": [], "article_count": 1}'
)


def _test_entity_chain() -> Runnable[EntityExtractionInput, EntityExtractionOutput]:
    return build_entity_extraction_chain(MockLlm(response=_TEST_ENTITY_RESPONSE))


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

    audit_service = providers.Factory(AuditService, repo=audit_repo)
    auth_service = providers.Factory(AuthService, user_repo=user_repo)
    broadcaster = providers.Singleton(EventBroadcaster)

    text_extractor = providers.Object(
        lambda _b, _f: ExtractionResult(
            text=_TEST_TEXT, extractor_used="test", char_count=len(_TEST_TEXT)
        )
    )
    # Generous cap -- shouldn't gate tests, just needs to satisfy the now-required param.
    extraction_semaphore = providers.Singleton(asyncio.Semaphore, 100)
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
    coordinator = providers.Factory(
        build_coordinator,
        node1=node1,
        node2=node2,
        node3=node3,
        node4=node4,
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
    )

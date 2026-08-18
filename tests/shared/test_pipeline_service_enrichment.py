import asyncio
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from fastapi import BackgroundTasks

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.database.repositories.document_steps import InMemoryDocumentStepsRepository
from classiflow.database.repositories.enriched_record import InMemoryEnrichedRecordRepository
from classiflow.database.repositories.hash import InMemoryHashRepository
from classiflow.database.repositories.job import InMemoryJobRepository
from classiflow.enrichment.coordinator import build_enrichment_coordinator
from classiflow.enrichment.nodes import EntityExtractorNode, MetadataEnricherNode, TextCleanerNode
from classiflow.enrichment.prompts.entity_extraction import build_entity_extraction_chain
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
from classiflow.ingesta.prompts import build_content_chain
from classiflow.services.audit.service import AuditService
from classiflow.services.pipeline.service import PipelineService

_SPANISH_TEXT = (
    "El Concejo Municipal de Rosario sanciona la siguiente ordenanza: "
    "Artículo 1º — Apruébase el presupuesto municipal para el ejercicio fiscal "
    "correspondiente al año en curso, conforme al detalle que se adjunta."
)
_MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"xref\n0 1\n0000000000 65535 f\ntrailer\n<< /Size 1 >>\nstartxref\n9\n%%EOF"
)
_SLM_LEGITIMATE = '{"is_legitimate": true, "confidence": 0.92, "reasoning": "ok"}'
_VALID_ENTITY_RESPONSE = (
    '{"doc_type_hint": "ordenanza", "number": "1", "year": 2024, '
    '"issuing_body": "Concejo Municipal", "signatories": [], "article_count": 1}'
)


def _stub_embed(_text: str) -> npt.NDArray[np.float32]:
    return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


@dataclass
class _MockIsoCode:
    name: str


@dataclass
class _MockLanguage:
    iso_code_639_1: _MockIsoCode


class _MockDetector:
    def __init__(self, iso_code: str) -> None:
        self._iso_code = iso_code

    def detect_language_of(self, _text: str) -> _MockLanguage:
        return _MockLanguage(_MockIsoCode(self._iso_code))


@dataclass
class _ServiceUnderTest:
    service: PipelineService
    job_repo: InMemoryJobRepository
    enriched_record_repo: InMemoryEnrichedRecordRepository


def _build_service(entity_response: str) -> _ServiceUnderTest:
    audit = AuditService(InMemoryAuditRepository())
    broadcaster = EventBroadcaster()

    n1 = FileReceptionNode(
        audit=audit, broadcaster=broadcaster, mime_detector=lambda _b: "application/pdf"
    )
    n2 = FormatValidationNode(audit=audit, broadcaster=broadcaster)
    extraction_step = ExtractionStep(
        audit=audit,
        broadcaster=broadcaster,
        text_extractor=lambda *_: ExtractionResult(
            text=_SPANISH_TEXT, extractor_used="test", char_count=len(_SPANISH_TEXT)
        ),
        semaphore=asyncio.Semaphore(10),
    )
    n3 = ContentValidationNode(
        audit=audit,
        broadcaster=broadcaster,
        language_detector=_MockDetector("es"),
        content_chain=build_content_chain(MockLlm(response=_SLM_LEGITIMATE)),
    )
    n4 = DuplicateControlNode(
        hash_repo=InMemoryHashRepository(),
        audit=audit,
        broadcaster=broadcaster,
        embedding_store=EmbeddingStore(dim=4, embed_fn=_stub_embed),
    )
    coordinator = build_coordinator(n1, n2, n3, n4, extraction_step=extraction_step)

    text_cleaner = TextCleanerNode(audit=audit, broadcaster=broadcaster)
    entity_extractor = EntityExtractorNode(
        audit=audit,
        broadcaster=broadcaster,
        entity_chain=build_entity_extraction_chain(MockLlm(response=entity_response)),
    )
    metadata_enricher = MetadataEnricherNode(audit=audit, broadcaster=broadcaster)
    enrichment_coordinator = build_enrichment_coordinator(
        text_cleaner, entity_extractor, metadata_enricher
    )

    job_repo = InMemoryJobRepository()
    enriched_record_repo = InMemoryEnrichedRecordRepository()
    service = PipelineService(
        job_repo=job_repo,
        document_steps_repo=InMemoryDocumentStepsRepository(),
        enriched_record_repo=enriched_record_repo,
        broadcaster=broadcaster,
        coordinator=coordinator,
        enrichment_coordinator=enrichment_coordinator,
    )
    return _ServiceUnderTest(
        service=service, job_repo=job_repo, enriched_record_repo=enriched_record_repo
    )


class TestPipelineServiceEnrichmentHappyPath:
    async def test_accepted_job_gets_enriched_record(self) -> None:
        under_test = _build_service(_VALID_ENTITY_RESPONSE)
        background_tasks = BackgroundTasks()
        job_id = await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        job = await under_test.job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status == "accepted"

        record = await under_test.enriched_record_repo.find_by_job_id(job_id)
        assert record is not None
        assert "Artículo 1" in record.cleaned_text
        assert record.entities["doc_type_hint"] == "ordenanza"
        assert record.metadata_["source"] == "manual_upload"


class TestPipelineServiceEnrichmentFailurePath:
    async def test_enrichment_failure_marks_job_for_review(self) -> None:
        under_test = _build_service("not json at all")
        background_tasks = BackgroundTasks()
        job_id = await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        job = await under_test.job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status == "review"
        assert job.review_action_needed == "enrichment_failed"
        assert job.failed_at_node == "enrichment"
        assert "Enrichment failed after retries" in (job.rejection_reason or "")

        record = await under_test.enriched_record_repo.find_by_job_id(job_id)
        assert record is None

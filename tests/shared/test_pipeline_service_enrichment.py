import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import anyio
import numpy as np
import numpy.typing as npt
from fastapi import BackgroundTasks

from classiflow.classification.config_classification import ClassificationConfig
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
from classiflow.classification.prompts.llm_judge import build_judge_chain
from classiflow.classification.prompts.primary_classification import build_classification_chain
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.database.repositories.classification_record import (
    InMemoryClassificationRecordRepository,
)
from classiflow.database.repositories.document_steps import InMemoryDocumentStepsRepository
from classiflow.database.repositories.enriched_record import InMemoryEnrichedRecordRepository
from classiflow.database.repositories.hash import InMemoryHashRepository
from classiflow.database.repositories.job import InMemoryJobRepository
from classiflow.domain.job import JobStatus, NodeEvent
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
from classiflow.storage.document_storage import LocalDiskStorage

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

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
_HIGH_CONFIDENCE_PRIMARY_RESPONSE = (
    '{"label": "ordenanzas", "confidence": 0.95, "reasoning": "clear match"}'
)
_JUDGE_ACCEPT_RESPONSE = '{"accept": true, "final_label": "ordenanzas", "reasoning": "ok"}'


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
    broadcaster: EventBroadcaster


def _build_service(
    entity_response: str,
    tmp_path: Path,
    *,
    coordinator_override: "CompiledStateGraph | None" = None,  # type: ignore[type-arg]
) -> _ServiceUnderTest:
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

    classification_config = ClassificationConfig(second_opinion_enabled=False)
    classification_coordinator = build_classification_coordinator(
        PrimaryClassifierNode(
            audit=audit,
            broadcaster=broadcaster,
            classification_chain=build_classification_chain(
                MockLlm(response=_HIGH_CONFIDENCE_PRIMARY_RESPONSE)
            ),
            config=classification_config,
        ),
        SecondOpinionNode(audit=audit, broadcaster=broadcaster, config=classification_config),
        ForeignMunicipalityNode(audit=audit, broadcaster=broadcaster, config=classification_config),
        SmellsRiskNode(audit=audit, broadcaster=broadcaster, config=classification_config),
        ConfidenceGateNode(audit=audit, broadcaster=broadcaster, config=classification_config),
        LlmJudgeNode(
            audit=audit,
            broadcaster=broadcaster,
            judge_chain=build_judge_chain(MockLlm(response=_JUDGE_ACCEPT_RESPONSE)),
        ),
        RoutingNode(
            audit=audit,
            broadcaster=broadcaster,
            storage=LocalDiskStorage(root=str(tmp_path)),
            classification_repo=InMemoryClassificationRecordRepository(),
        ),
    )

    job_repo = InMemoryJobRepository()
    enriched_record_repo = InMemoryEnrichedRecordRepository()
    service = PipelineService(
        job_repo=job_repo,
        document_steps_repo=InMemoryDocumentStepsRepository(),
        enriched_record_repo=enriched_record_repo,
        broadcaster=broadcaster,
        coordinator=coordinator if coordinator_override is None else coordinator_override,
        enrichment_coordinator=enrichment_coordinator,
        document_storage=LocalDiskStorage(root=str(tmp_path)),
        classification_coordinator=classification_coordinator,
        job_semaphore=asyncio.Semaphore(10),
    )
    return _ServiceUnderTest(
        service=service,
        job_repo=job_repo,
        enriched_record_repo=enriched_record_repo,
        broadcaster=broadcaster,
    )


class TestPipelineServiceEnrichmentHappyPath:
    async def test_accepted_job_gets_enriched_record(self, tmp_path: Path) -> None:
        under_test = _build_service(_VALID_ENTITY_RESPONSE, tmp_path)
        background_tasks = BackgroundTasks()
        job_id = await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        job = await under_test.job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status == "classified"

        record = await under_test.enriched_record_repo.find_by_job_id(job_id)
        assert record is not None
        assert "Artículo 1" in record.cleaned_text
        assert record.raw_text == _SPANISH_TEXT
        assert record.entities["doc_type_hint"] == "ordenanza"
        assert record.metadata_["source"] == "manual_upload"


class TestPipelineServiceEnrichmentFailurePath:
    async def test_enrichment_failure_marks_job_for_review(self, tmp_path: Path) -> None:
        under_test = _build_service("not json at all", tmp_path)
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


class TestPipelineServiceStaging:
    async def test_accepted_job_stages_file_bytes(self, tmp_path: Path) -> None:
        # Since Task 16 chains classification straight after enrichment, RoutingNode
        # moves the staged file to its final classified/<label>/ location before this
        # assertion runs -- it no longer sits in staging/ at test-completion time. The
        # file existing at its final destination, with the original bytes intact,
        # still proves staging happened correctly (RoutingNode's move_to_final can only
        # find and move a file that was staged in the first place).
        under_test = _build_service(_VALID_ENTITY_RESPONSE, tmp_path)
        background_tasks = BackgroundTasks()
        job_id = await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        final_path = anyio.Path(tmp_path / "classified" / "ordenanzas" / f"{job_id}_ordenanza.pdf")
        assert await final_path.exists()
        assert await final_path.read_bytes() == _MINIMAL_PDF

    async def test_job_rejected_before_extraction_is_never_staged(self, tmp_path: Path) -> None:
        # A fake coordinator standing in for "node2 rejected the file before extraction"
        # -- final_state has no "extraction" key, the exact condition _run() gates
        # save_staged on. Injected via _build_service rather than patching the private
        # attribute, keeping the test on the constructor seam.
        class _RejectsBeforeExtractionCoordinator:
            async def ainvoke(self, state: dict[str, object]) -> dict[str, object]:
                return {
                    "job_id": state["job_id"],
                    "filename": state["filename"],
                    "final_status": "rejected",
                    "rejection_reason": "bad format",
                }

        under_test = _build_service(
            _VALID_ENTITY_RESPONSE,
            tmp_path,
            coordinator_override=cast("CompiledStateGraph", _RejectsBeforeExtractionCoordinator()),
        )
        background_tasks = BackgroundTasks()
        job_id = await under_test.service.start(background_tasks, "bad.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        job = await under_test.job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status == "rejected"
        assert not await anyio.Path(tmp_path / "staging" / f"{job_id}_bad.pdf").exists()


class TestPipelineServiceQueuedProcessing:
    async def test_job_starts_as_queued(self, tmp_path: Path) -> None:
        under_test = _build_service(_VALID_ENTITY_RESPONSE, tmp_path)
        background_tasks = BackgroundTasks()

        job_id = await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)

        job = await under_test.job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status == "queued"

    async def test_job_moves_past_queued_once_run(self, tmp_path: Path) -> None:
        under_test = _build_service(_VALID_ENTITY_RESPONSE, tmp_path)
        background_tasks = BackgroundTasks()
        job_id = await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        job = await under_test.job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status != "queued"

    async def test_broadcasts_processing_event_once_semaphore_acquired(
        self, tmp_path: Path
    ) -> None:
        under_test = _build_service(_VALID_ENTITY_RESPONSE, tmp_path)
        background_tasks = BackgroundTasks()
        job_id = await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)

        received: list[NodeEvent] = []

        async def _consume() -> None:
            received.extend([event async for event in under_test.broadcaster.subscribe(job_id)])

        consume_task = asyncio.create_task(_consume())
        for task in background_tasks.tasks:
            await task()
        await consume_task

        statuses = [e.status for e in received]
        assert JobStatus.PROCESSING in statuses

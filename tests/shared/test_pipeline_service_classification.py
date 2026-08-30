import asyncio
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import numpy.typing as npt
import pytest
from fastapi import BackgroundTasks
from langgraph.graph.state import CompiledStateGraph

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
from classiflow.database.repositories.document_kb import InMemoryDocumentKbRepository
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
from classiflow.services.pipeline.service import PipelineService, is_pipeline_busy
from classiflow.storage.document_storage import LocalDiskStorage
from tests.fakes import make_indexer

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
    classification_record_repo: InMemoryClassificationRecordRepository
    # Exposes the same coordinator instance PipelineService holds internally, so
    # tests can patch/spy its `ainvoke` without reaching into a private attribute.
    coordinator: CompiledStateGraph  # type: ignore[type-arg]


def _build_service(tmp_path: Path) -> _ServiceUnderTest:
    audit = AuditService(InMemoryAuditRepository())
    broadcaster = EventBroadcaster()
    storage = LocalDiskStorage(root=str(tmp_path))

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
        entity_chain=build_entity_extraction_chain(MockLlm(response=_VALID_ENTITY_RESPONSE)),
    )
    metadata_enricher = MetadataEnricherNode(audit=audit, broadcaster=broadcaster)
    enrichment_coordinator = build_enrichment_coordinator(
        text_cleaner, entity_extractor, metadata_enricher
    )

    classification_config = ClassificationConfig(second_opinion_enabled=False)
    primary_classifier = PrimaryClassifierNode(
        audit=audit,
        broadcaster=broadcaster,
        classification_chain=build_classification_chain(
            MockLlm(response=_HIGH_CONFIDENCE_PRIMARY_RESPONSE)
        ),
        config=classification_config,
    )
    second_opinion = SecondOpinionNode(
        audit=audit, broadcaster=broadcaster, config=classification_config
    )
    foreign_municipality = ForeignMunicipalityNode(
        audit=audit, broadcaster=broadcaster, config=classification_config
    )
    smells_risk = SmellsRiskNode(audit=audit, broadcaster=broadcaster, config=classification_config)
    confidence_gate = ConfidenceGateNode(
        audit=audit, broadcaster=broadcaster, config=classification_config
    )
    llm_judge = LlmJudgeNode(
        audit=audit,
        broadcaster=broadcaster,
        judge_chain=build_judge_chain(MockLlm(response=_JUDGE_ACCEPT_RESPONSE)),
    )
    classification_record_repo = InMemoryClassificationRecordRepository()
    routing = RoutingNode(
        audit=audit,
        broadcaster=broadcaster,
        storage=storage,
        classification_repo=classification_record_repo,
    )
    classification_coordinator = build_classification_coordinator(
        primary_classifier,
        second_opinion,
        foreign_municipality,
        smells_risk,
        confidence_gate,
        llm_judge,
        routing,
    )

    job_repo = InMemoryJobRepository()
    service = PipelineService(
        job_repo=job_repo,
        document_steps_repo=InMemoryDocumentStepsRepository(),
        enriched_record_repo=InMemoryEnrichedRecordRepository(),
        broadcaster=broadcaster,
        coordinator=coordinator,
        enrichment_coordinator=enrichment_coordinator,
        document_storage=storage,
        classification_coordinator=classification_coordinator,
        job_semaphore=asyncio.Semaphore(10),
        indexer=make_indexer(),
        document_kb_repo=InMemoryDocumentKbRepository(),
    )
    return _ServiceUnderTest(
        service=service,
        job_repo=job_repo,
        classification_record_repo=classification_record_repo,
        coordinator=coordinator,
    )


class TestPipelineServiceGpuMemory:
    async def test_gpu_models_are_released_even_when_a_node_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        EXPECTED_UNLOAD_CALL_COUNT = 2  # once at job start, once in `finally`

        under_test = _build_service(tmp_path)

        monkeypatch.setattr(
            under_test.coordinator, "ainvoke", AsyncMock(side_effect=RuntimeError("node exploded"))
        )

        calls: list[str] = []
        monkeypatch.setattr(
            "classiflow.services.pipeline.service.unload_slm", lambda: calls.append("slm")
        )
        monkeypatch.setattr(
            "classiflow.services.pipeline.service.unload_bert", lambda: calls.append("bert")
        )
        monkeypatch.setattr(
            "classiflow.services.pipeline.service.unload_chat_llm", lambda: calls.append("chat")
        )
        monkeypatch.setattr(
            "classiflow.services.pipeline.service.unload_kb_embedder",
            lambda: calls.append("kb_embedder"),
        )
        monkeypatch.setattr(
            "classiflow.services.pipeline.service.unload_duplicate_control_embedder",
            lambda: calls.append("duplicate_control_embedder"),
        )

        background_tasks = BackgroundTasks()
        await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        (run_task,) = background_tasks.tasks
        with pytest.raises(RuntimeError):
            await run_task()

        # Called once at start (nothing to evict yet, still a real call) and once in `finally`.
        assert calls.count("slm") == EXPECTED_UNLOAD_CALL_COUNT
        assert calls.count("bert") == EXPECTED_UNLOAD_CALL_COUNT
        assert calls.count("chat") == EXPECTED_UNLOAD_CALL_COUNT
        assert calls.count("kb_embedder") == EXPECTED_UNLOAD_CALL_COUNT
        assert calls.count("duplicate_control_embedder") == EXPECTED_UNLOAD_CALL_COUNT

    async def test_is_pipeline_busy_is_true_only_while_a_job_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        under_test = _build_service(tmp_path)
        assert is_pipeline_busy() is False

        observed: list[bool] = []
        original_ainvoke = under_test.coordinator.ainvoke

        async def _spy_ainvoke(*args: object, **kwargs: object) -> object:
            observed.append(is_pipeline_busy())
            return await original_ainvoke(*args, **kwargs)

        monkeypatch.setattr(under_test.coordinator, "ainvoke", _spy_ainvoke)

        background_tasks = BackgroundTasks()
        await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        assert observed == [True]
        assert is_pipeline_busy() is False


class TestPipelineServiceClassification:
    async def test_accepted_job_reaches_classification_and_persists_record(
        self, tmp_path: Path
    ) -> None:
        under_test = _build_service(tmp_path)
        background_tasks = BackgroundTasks()
        job_id = await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        job = await under_test.job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status == "classified"

        record = await under_test.classification_record_repo.find_by_job_id(job_id)
        assert record is not None
        assert record.label == "ordenanzas"
        assert record.review_route == "accept"
        assert record.stored_path is not None
        assert Path("classified", "ordenanzas").as_posix() in Path(record.stored_path).as_posix()

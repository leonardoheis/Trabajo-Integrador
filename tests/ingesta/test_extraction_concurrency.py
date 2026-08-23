import asyncio
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import numpy as np
import numpy.typing as npt
import pytest
from langgraph.graph.state import CompiledStateGraph

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.database.repositories.document_steps import InMemoryDocumentStepsRepository
from classiflow.database.repositories.enriched_record import InMemoryEnrichedRecordRepository
from classiflow.database.repositories.hash import InMemoryHashRepository
from classiflow.database.repositories.job import InMemoryJobRepository
from classiflow.domain.job import JobStatus
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.coordinator import build_coordinator
from classiflow.ingesta.domain import ExtractionResult, JobContext
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
from classiflow.services.pipeline.service import PipelineService
from tests.fakes import make_indexing_node

if TYPE_CHECKING:
    from classiflow.database.models import DocumentStep
    from classiflow.ingesta.domain import JobState
    from classiflow.storage.document_storage import IDocumentStorage

_MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"xref\n0 1\n0000000000 65535 f\ntrailer\n<< /Size 1 >>\nstartxref\n9\n%%EOF"
)
_SPANISH_TEXT = (
    "El Concejo Municipal de Rosario sanciona la siguiente ordenanza: "
    "Artículo 1º — Apruébase el presupuesto municipal para el ejercicio fiscal "
    "correspondiente al año en curso, conforme al detalle que se adjunta como Anexo I."
)
_SLM_LEGITIMATE = '{"is_legitimate": true, "confidence": 0.92, "reasoning": "official doc"}'
_DIM = 4


class _ConcurrencyTrackingExtractor:
    """Records the max number of simultaneous in-flight calls it ever saw."""

    def __init__(self, delay_seconds: float = 0.05) -> None:
        self._delay_seconds = delay_seconds
        self._lock = threading.Lock()
        self._current = 0
        self.max_observed = 0

    def __call__(self, _file_bytes: bytes, _filename: str) -> ExtractionResult:
        with self._lock:
            self._current += 1
            self.max_observed = max(self.max_observed, self._current)
        time.sleep(self._delay_seconds)  # runs in a real thread (asyncio.to_thread)
        with self._lock:
            self._current -= 1
        return ExtractionResult(text="x" * 30, extractor_used="tracked", char_count=30)


async def test_concurrency_cap_holds_under_simulated_load() -> None:
    cap = 2
    tracker = _ConcurrencyTrackingExtractor()
    step = ExtractionStep(
        audit=AuditService(InMemoryAuditRepository()),
        broadcaster=EventBroadcaster(),
        text_extractor=tracker,
        semaphore=asyncio.Semaphore(cap),
    )

    job_count = 6
    await asyncio.gather(*[
        step.run(JobContext(job_id=f"job-{i}", filename="f.pdf"), b"x", "f.pdf")
        for i in range(job_count)
    ])

    assert tracker.max_observed <= cap
    # A cap this tight with this many concurrent jobs and an artificial delay should
    # actually get exercised, not just happen to never collide -- otherwise this test
    # would pass even if the semaphore were silently not applied at all.
    assert tracker.max_observed == cap


def _stub_embed(_text: str) -> npt.NDArray[np.float32]:
    return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


def _stub_mime(_file_bytes: bytes) -> str:
    return "application/pdf"


def _build_graph(
    audit: AuditService, broadcaster: EventBroadcaster, hash_repo: InMemoryHashRepository
) -> CompiledStateGraph:  # type: ignore[type-arg]
    n1 = FileReceptionNode(audit=audit, broadcaster=broadcaster, mime_detector=_stub_mime)
    n2 = FormatValidationNode(audit=audit, broadcaster=broadcaster)
    extraction_step = ExtractionStep(
        audit=audit,
        broadcaster=broadcaster,
        text_extractor=lambda *_: ExtractionResult(
            text=_SPANISH_TEXT, extractor_used="markitdown", char_count=len(_SPANISH_TEXT)
        ),
        semaphore=asyncio.Semaphore(10),
    )
    n3 = ContentValidationNode(
        audit=audit, broadcaster=broadcaster, language_detector=_MockDetector("es")
    )
    n4 = DuplicateControlNode(
        hash_repo=hash_repo,
        audit=audit,
        broadcaster=broadcaster,
        embedding_store=EmbeddingStore(dim=_DIM, embed_fn=_stub_embed),
    )
    n5 = make_indexing_node(audit, broadcaster)
    return build_coordinator(n1, n2, n3, n4, n5, extraction_step=extraction_step)


async def test_extraction_events_appear_between_node2_and_node3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "classiflow.ingesta.nodes.node3_content_validation.get_llm_langchain",
        lambda _path: MockLlm(response=_SLM_LEGITIMATE),
    )
    audit = AuditService(InMemoryAuditRepository())
    broadcaster = EventBroadcaster()
    graph = _build_graph(audit, broadcaster, InMemoryHashRepository())
    job_id = "sse-order-job"

    events: list[object] = []

    async def collect() -> None:
        events.extend([event async for event in broadcaster.subscribe(job_id)])

    collect_task = asyncio.create_task(collect())
    await asyncio.sleep(0)
    initial: JobState = {"job_id": job_id, "filename": "doc.pdf", "file_bytes": _MINIMAL_PDF}
    await graph.ainvoke(initial)
    await broadcaster.close(job_id)
    await collect_task

    node_order = [event.node for event in events]  # type: ignore[attr-defined]
    extraction_index = node_order.index("extraction")
    node2_last_index = max(i for i, n in enumerate(node_order) if n == "node2_format_validation")
    node3_first_index = min(i for i, n in enumerate(node_order) if n == "node3_content_validation")
    assert node2_last_index < extraction_index < node3_first_index
    assert [e.status for e in events if e.node == "extraction"] == [  # type: ignore[attr-defined]
        JobStatus.STARTED,
        JobStatus.PASSED,
    ]


async def test_extractor_used_is_queryable_from_document_step() -> None:
    document_steps_repo = InMemoryDocumentStepsRepository()
    service = PipelineService(
        job_repo=InMemoryJobRepository(),
        document_steps_repo=document_steps_repo,
        enriched_record_repo=InMemoryEnrichedRecordRepository(),  # unused: only _persist_steps runs
        broadcaster=EventBroadcaster(),
        coordinator=cast("CompiledStateGraph", None),  # unused: only _persist_steps runs
        enrichment_coordinator=cast("CompiledStateGraph", None),  # unused: only _persist_steps runs
        document_storage=cast("IDocumentStorage", None),  # unused: only _persist_steps runs
        classification_coordinator=cast(  # unused: only _persist_steps runs
            "CompiledStateGraph", None
        ),
        job_semaphore=asyncio.Semaphore(1),  # unused: only _persist_steps runs
    )
    job_id = "persisted-job"
    final_state: JobState = {
        "job_id": job_id,
        "filename": "doc.pdf",
        "file_bytes": _MINIMAL_PDF,
        "extraction": ExtractionResult(
            text=_SPANISH_TEXT, extractor_used="ocr", char_count=len(_SPANISH_TEXT)
        ),
    }

    await service._persist_steps(job_id, final_state)  # noqa: SLF001  (the thing under test)

    steps: list[DocumentStep] = await document_steps_repo.steps_for_job(job_id)
    extraction_steps = [s for s in steps if s.node == "extraction"]
    assert len(extraction_steps) == 1
    detail = extraction_steps[0].detail
    assert detail is not None
    assert detail["extractor_used"] == "ocr"
    assert detail["text"] == _SPANISH_TEXT


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

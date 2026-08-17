import asyncio

import pytest

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.domain.job import JobStatus
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.domain.context import JobContext
from classiflow.ingesta.domain.results import ExtractionResult
from classiflow.ingesta.nodes.extraction_step import ExtractionStep
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-extract"
_FILENAME = "sample.pdf"
_FILE_BYTES = b"%PDF-1.4 fake"
_STARTED_PLUS_OUTCOME_EVENTS = 2

_CTX = JobContext(job_id=_JOB_ID, filename=_FILENAME)
_EXTRACTED_TEXT = "Artículo 1º — texto de la ordenanza."
_RESULT = ExtractionResult(text=_EXTRACTED_TEXT, extractor_used="markitdown", char_count=37)


def _stub_extractor(_file_bytes: bytes, _filename: str) -> ExtractionResult:
    return _RESULT


@pytest.fixture
def audit_repo() -> InMemoryAuditRepository:
    return InMemoryAuditRepository()


@pytest.fixture
def audit(audit_repo: InMemoryAuditRepository) -> AuditService:
    return AuditService(audit_repo)


@pytest.fixture
def broadcaster() -> EventBroadcaster:
    return EventBroadcaster()


@pytest.fixture
def step(audit: AuditService, broadcaster: EventBroadcaster) -> ExtractionStep:
    return ExtractionStep(
        audit=audit,
        broadcaster=broadcaster,
        text_extractor=_stub_extractor,
        semaphore=asyncio.Semaphore(10),
    )


class TestExtractionStep:
    async def test_returns_the_extractor_result_unchanged(self, step: ExtractionStep) -> None:
        result = await step.run(_CTX, _FILE_BYTES, _FILENAME)

        assert result == _RESULT

    async def test_always_passes(
        self,
        step: ExtractionStep,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        # Extraction never rejects a document -- even an empty/unusable result still
        # reports passed=True; the "no usable text" judgment stays in node3.
        empty_result = ExtractionResult(text="", extractor_used="", char_count=0)
        empty_step = ExtractionStep(
            audit=step.audit,
            broadcaster=step.broadcaster,
            text_extractor=lambda _b, _f: empty_result,
            semaphore=asyncio.Semaphore(10),
        )
        result = await empty_step.run(_CTX, _FILE_BYTES, _FILENAME)

        assert result.passed
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == JobStatus.PASSED.value

    async def test_audit_detail_has_metadata_not_full_text(
        self,
        step: ExtractionStep,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        await step.run(_CTX, _FILE_BYTES, _FILENAME)

        records = await audit_repo.list_for_job(_JOB_ID)
        detail = records[0].detail
        assert detail is not None
        assert detail["extractor_used"] == "markitdown"
        assert detail["char_count"] == _RESULT.char_count
        assert "text" not in detail

    async def test_emits_started_then_passed(
        self,
        step: ExtractionStep,
        broadcaster: EventBroadcaster,
    ) -> None:
        events: list[object] = []

        async def collect() -> None:
            events.extend([event async for event in broadcaster.subscribe(_JOB_ID)])

        collect_task = asyncio.create_task(collect())
        await asyncio.sleep(0)  # yield so collect() starts subscribing before run() emits
        await step.run(_CTX, _FILE_BYTES, _FILENAME)
        await broadcaster.close(_JOB_ID)
        await collect_task

        assert len(events) == _STARTED_PLUS_OUTCOME_EVENTS
        assert events[0].status == JobStatus.STARTED  # type: ignore[union-attr]
        assert events[0].node == "extraction"  # type: ignore[union-attr]
        assert events[1].status == JobStatus.PASSED  # type: ignore[union-attr]
        assert events[1].node == "extraction"  # type: ignore[union-attr]

    async def test_audit_records_duration(
        self,
        step: ExtractionStep,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        await step.run(_CTX, _FILE_BYTES, _FILENAME)

        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].duration_ms is not None
        assert records[0].duration_ms >= 0

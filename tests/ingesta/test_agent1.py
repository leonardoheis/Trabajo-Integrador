import asyncio
import hashlib

import pytest

from classiflow.ingesta.agents.agent1_file_reception import AGENT_NAME, FileReceptionAgent
from classiflow.shared.audit.service import AuditService
from classiflow.shared.database.repositories.audit import InMemoryAuditRepository
from classiflow.shared.domain.job import JobStatus
from classiflow.shared.events.broadcaster import EventBroadcaster

_MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"xref\n0 1\n0000000000 65535 f\ntrailer\n<< /Size 1 >>\nstartxref\n9\n%%EOF"
)
_JOB_ID = "test-job-001"
_FILENAME = "sample.pdf"
_PDF_MIME = "application/pdf"
_OVERSIZED_CONTENT_SIZE = 11
_SHA256_HEX_LENGTH = 64
_STARTED_PLUS_OUTCOME_EVENTS = 2


def _stub_mime(_data: bytes) -> str:
    return _PDF_MIME


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
def agent(audit: AuditService, broadcaster: EventBroadcaster) -> FileReceptionAgent:
    return FileReceptionAgent(audit=audit, broadcaster=broadcaster, mime_detector=_stub_mime)


class TestFileReceptionAgent:
    async def test_missing_file_fails(
        self,
        agent: FileReceptionAgent,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        result = await agent.run(_JOB_ID, _FILENAME, None)

        assert not result.passed
        assert "No file" in result.rejection_reason
        records = await audit_repo.list_for_job(_JOB_ID)
        assert len(records) == 1
        assert records[0].event == JobStatus.FAILED.value

    async def test_empty_file_fails(
        self,
        agent: FileReceptionAgent,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        result = await agent.run(_JOB_ID, _FILENAME, b"")

        assert not result.passed
        assert "empty" in result.rejection_reason.lower()
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == JobStatus.FAILED.value

    async def test_oversized_file_fails(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        small_limit_agent = FileReceptionAgent(
            audit=audit,
            broadcaster=broadcaster,
            max_file_size_bytes=10,
            mime_detector=_stub_mime,
        )
        result = await small_limit_agent.run(_JOB_ID, _FILENAME, b"x" * _OVERSIZED_CONTENT_SIZE)

        assert not result.passed
        assert result.file_size_bytes == _OVERSIZED_CONTENT_SIZE
        assert "exceeds" in result.rejection_reason.lower()
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == JobStatus.FAILED.value

    async def test_valid_pdf_passes(
        self,
        agent: FileReceptionAgent,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        result = await agent.run(_JOB_ID, _FILENAME, _MINIMAL_PDF)

        assert result.passed
        assert result.sha256 == hashlib.sha256(_MINIMAL_PDF).hexdigest()
        assert len(result.sha256) == _SHA256_HEX_LENGTH
        assert result.detected_mime == _PDF_MIME
        assert result.file_size_bytes == len(_MINIMAL_PDF)
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == JobStatus.PASSED.value

    async def test_emits_started_then_passed(
        self,
        agent: FileReceptionAgent,
        broadcaster: EventBroadcaster,
    ) -> None:
        events: list[object] = []

        async def collect() -> None:
            events.extend([event async for event in broadcaster.subscribe(_JOB_ID)])

        collect_task = asyncio.create_task(collect())
        await asyncio.sleep(0)  # yield so collect() starts subscribing before run() emits
        await agent.run(_JOB_ID, _FILENAME, _MINIMAL_PDF)
        await broadcaster.close(_JOB_ID)
        await collect_task

        assert len(events) == _STARTED_PLUS_OUTCOME_EVENTS
        assert events[0].status == JobStatus.STARTED  # type: ignore[union-attr]
        assert events[0].agent == AGENT_NAME  # type: ignore[union-attr]
        assert events[1].status == JobStatus.PASSED  # type: ignore[union-attr]
        assert events[1].agent == AGENT_NAME  # type: ignore[union-attr]

    async def test_emits_started_then_failed(
        self,
        agent: FileReceptionAgent,
        broadcaster: EventBroadcaster,
    ) -> None:
        events: list[object] = []

        async def collect() -> None:
            events.extend([event async for event in broadcaster.subscribe(_JOB_ID)])

        collect_task = asyncio.create_task(collect())
        await asyncio.sleep(0)  # yield so collect() starts subscribing before run() emits
        await agent.run(_JOB_ID, _FILENAME, None)
        await broadcaster.close(_JOB_ID)
        await collect_task

        assert len(events) == _STARTED_PLUS_OUTCOME_EVENTS
        assert events[0].status == JobStatus.STARTED  # type: ignore[union-attr]
        assert events[1].status == JobStatus.FAILED  # type: ignore[union-attr]

    async def test_audit_records_duration(
        self,
        agent: FileReceptionAgent,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        await agent.run(_JOB_ID, _FILENAME, _MINIMAL_PDF)

        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].duration_ms is not None
        assert records[0].duration_ms >= 0

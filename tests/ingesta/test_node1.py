import asyncio
import hashlib

import pytest

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.domain.job import JobStatus
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.domain.context import JobContext
from classiflow.ingesta.nodes.node1_file_reception import FileReceptionNode
from classiflow.services.audit.service import AuditService

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

_CTX = JobContext(job_id=_JOB_ID, filename=_FILENAME)


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
def node(audit: AuditService, broadcaster: EventBroadcaster) -> FileReceptionNode:
    return FileReceptionNode(audit=audit, broadcaster=broadcaster, mime_detector=_stub_mime)


class TestFileReceptionNode:
    async def test_missing_file_fails(
        self,
        node: FileReceptionNode,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        result = await node.run(_CTX, None)

        assert not result.passed
        assert "No file" in result.rejection_reason
        records = await audit_repo.list_for_job(_JOB_ID)
        assert len(records) == 1
        assert records[0].event == JobStatus.FAILED.value

    async def test_empty_file_fails(
        self,
        node: FileReceptionNode,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        result = await node.run(_CTX, b"")

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
        small_limit_node = FileReceptionNode(
            audit=audit,
            broadcaster=broadcaster,
            max_file_size_bytes=10,
            mime_detector=_stub_mime,
        )
        result = await small_limit_node.run(_CTX, b"x" * _OVERSIZED_CONTENT_SIZE)

        assert not result.passed
        assert result.file_size_bytes == _OVERSIZED_CONTENT_SIZE
        assert "exceeds" in result.rejection_reason.lower()
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == JobStatus.FAILED.value

    async def test_valid_pdf_passes(
        self,
        node: FileReceptionNode,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        result = await node.run(_CTX, _MINIMAL_PDF)

        assert result.passed
        assert result.sha256 == hashlib.sha256(_MINIMAL_PDF).hexdigest()
        assert len(result.sha256) == _SHA256_HEX_LENGTH
        assert result.detected_mime == _PDF_MIME
        assert result.file_size_bytes == len(_MINIMAL_PDF)
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == JobStatus.PASSED.value

    async def test_emits_started_then_passed(
        self,
        node: FileReceptionNode,
        broadcaster: EventBroadcaster,
    ) -> None:
        events: list[object] = []

        async def collect() -> None:
            events.extend([event async for event in broadcaster.subscribe(_JOB_ID)])

        collect_task = asyncio.create_task(collect())
        await asyncio.sleep(0)  # yield so collect() starts subscribing before run() emits
        await node.run(_CTX, _MINIMAL_PDF)
        await broadcaster.close(_JOB_ID)
        await collect_task

        assert len(events) == _STARTED_PLUS_OUTCOME_EVENTS
        assert events[0].status == JobStatus.STARTED  # type: ignore[union-attr]
        assert events[0].node == "node1_file_reception"  # type: ignore[union-attr]
        assert events[1].status == JobStatus.PASSED  # type: ignore[union-attr]
        assert events[1].node == "node1_file_reception"  # type: ignore[union-attr]

    async def test_emits_started_then_failed(
        self,
        node: FileReceptionNode,
        broadcaster: EventBroadcaster,
    ) -> None:
        events: list[object] = []

        async def collect() -> None:
            events.extend([event async for event in broadcaster.subscribe(_JOB_ID)])

        collect_task = asyncio.create_task(collect())
        await asyncio.sleep(0)  # yield so collect() starts subscribing before run() emits
        await node.run(_CTX, None)
        await broadcaster.close(_JOB_ID)
        await collect_task

        assert len(events) == _STARTED_PLUS_OUTCOME_EVENTS
        assert events[0].status == JobStatus.STARTED  # type: ignore[union-attr]
        assert events[1].status == JobStatus.FAILED  # type: ignore[union-attr]

    async def test_audit_records_duration(
        self,
        node: FileReceptionNode,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        await node.run(_CTX, _MINIMAL_PDF)

        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].duration_ms is not None
        assert records[0].duration_ms >= 0

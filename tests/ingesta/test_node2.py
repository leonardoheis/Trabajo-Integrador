import asyncio

import pytest

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.domain.job import JobStatus
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.config import AllowedFormatsConfig
from classiflow.ingesta.domain import FileReceptionResult, FormatDecision, JobContext
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.ingesta.nodes import FormatValidationNode
from classiflow.ingesta.prompts import build_format_chain
from classiflow.services.audit.service import AuditService

_SLM_ACCEPT_RESPONSE = '{"decision": "accept", "confidence": 0.9, "reasoning": "valid format"}'
_SLM_REJECT_RESPONSE = '{"decision": "reject", "confidence": 0.85, "reasoning": "binary content"}'

_JOB_ID = "test-job-002"
_STARTED_PLUS_OUTCOME_EVENTS = 2

_CONFIG = AllowedFormatsConfig(
    allowed_mime_types=[
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/jpeg",
    ],
    allowed_extensions=[".pdf", ".docx", ".jpg", ".jpeg"],
    disabled_mime_types=["text/html", "application/xhtml+xml"],
    disabled_extensions=[".html", ".htm"],
    mime_to_extensions={
        "application/pdf": [".pdf"],
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
        "image/jpeg": [".jpg", ".jpeg"],
    },
    max_file_size_mb=50,
    known_mismatches={"application/zip": [".docx"]},
)


def _reception(mime: str = "application/pdf") -> FileReceptionResult:
    return FileReceptionResult(
        passed=True,
        sha256="abc123",
        detected_mime=mime,
        file_size_bytes=1024,
    )


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
def node(audit: AuditService, broadcaster: EventBroadcaster) -> FormatValidationNode:
    return FormatValidationNode(audit=audit, broadcaster=broadcaster, config=_CONFIG)


class TestRuleBasedCheck:
    def test_pdf_with_matching_extension_is_accepted(self, node: FormatValidationNode) -> None:
        result = node.rule_based_check("sample.pdf", "application/pdf")
        assert result == FormatDecision.ACCEPT

    def test_html_mime_is_rejected(self, node: FormatValidationNode) -> None:
        result = node.rule_based_check("page.html", "text/html")
        assert result == FormatDecision.REJECT

    def test_html_extension_is_rejected_even_with_unknown_mime(
        self, node: FormatValidationNode
    ) -> None:
        result = node.rule_based_check("file.html", "application/octet-stream")
        assert result == FormatDecision.REJECT

    def test_unknown_mime_triggers_manual_review(self, node: FormatValidationNode) -> None:
        result = node.rule_based_check("file.xyz", "application/x-unknown")
        assert result == FormatDecision.MANUAL_REVIEW

    def test_mime_extension_mismatch_escalates_to_slm(self, node: FormatValidationNode) -> None:
        # PDF magic bytes but .docx extension → gray zone
        result = node.rule_based_check("document.docx", "application/pdf")
        assert result == FormatDecision.SLM_ESCALATE

    def test_jpeg_with_both_valid_extensions(self, node: FormatValidationNode) -> None:
        assert node.rule_based_check("photo.jpg", "image/jpeg") == FormatDecision.ACCEPT
        assert node.rule_based_check("photo.jpeg", "image/jpeg") == FormatDecision.ACCEPT

    def test_known_mismatch_is_accepted_without_slm(self, node: FormatValidationNode) -> None:
        # libmagic detects DOCX as application/zip because DOCX is a ZIP archive
        result = node.rule_based_check("report.docx", "application/zip")
        assert result == FormatDecision.ACCEPT


class TestFormatValidationNodeRun:
    async def test_pdf_passes(
        self,
        node: FormatValidationNode,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        ctx = JobContext(job_id=_JOB_ID, filename="sample.pdf")
        result = await node.run(ctx, _reception("application/pdf"))

        assert result.passed
        assert result.decision == FormatDecision.ACCEPT
        assert not result.used_slm
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == JobStatus.PASSED.value

    async def test_html_fails(
        self,
        node: FormatValidationNode,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        ctx = JobContext(job_id=_JOB_ID, filename="page.html")
        result = await node.run(ctx, _reception("text/html"))

        assert not result.passed
        assert result.decision == FormatDecision.REJECT
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == JobStatus.FAILED.value

    async def test_unknown_mime_fails_with_manual_review(
        self,
        node: FormatValidationNode,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        ctx = JobContext(job_id=_JOB_ID, filename="file.xyz")
        result = await node.run(ctx, _reception("application/x-unknown"))

        assert not result.passed
        assert result.decision == FormatDecision.MANUAL_REVIEW
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == JobStatus.FAILED.value

    async def test_slm_accept_on_mime_extension_mismatch(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
    ) -> None:
        slm_node = FormatValidationNode(
            audit=audit,
            broadcaster=broadcaster,
            config=_CONFIG,
            format_chain=build_format_chain(MockLlm(response=_SLM_ACCEPT_RESPONSE)),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="document.docx")
        result = await slm_node.run(ctx, _reception("application/pdf"))

        assert result.passed
        assert result.decision == FormatDecision.ACCEPT
        assert result.used_slm

    async def test_slm_reject_on_mime_extension_mismatch(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
    ) -> None:
        slm_node = FormatValidationNode(
            audit=audit,
            broadcaster=broadcaster,
            config=_CONFIG,
            format_chain=build_format_chain(MockLlm(response=_SLM_REJECT_RESPONSE)),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="document.docx")
        result = await slm_node.run(ctx, _reception("application/pdf"))

        assert not result.passed
        assert result.decision == FormatDecision.REJECT
        assert result.used_slm
        assert "SLM:" in result.rejection_reason

    async def test_emits_started_then_passed(
        self,
        node: FormatValidationNode,
        broadcaster: EventBroadcaster,
    ) -> None:
        events: list[object] = []

        async def collect() -> None:
            events.extend([event async for event in broadcaster.subscribe(_JOB_ID)])

        collect_task = asyncio.create_task(collect())
        await asyncio.sleep(0)
        ctx = JobContext(job_id=_JOB_ID, filename="sample.pdf")
        await node.run(ctx, _reception("application/pdf"))
        await broadcaster.close(_JOB_ID)
        await collect_task

        assert len(events) == _STARTED_PLUS_OUTCOME_EVENTS
        assert events[0].status == JobStatus.STARTED  # type: ignore[union-attr]
        assert events[1].status == JobStatus.PASSED  # type: ignore[union-attr]

    async def test_emits_started_then_failed(
        self,
        node: FormatValidationNode,
        broadcaster: EventBroadcaster,
    ) -> None:
        events: list[object] = []

        async def collect() -> None:
            events.extend([event async for event in broadcaster.subscribe(_JOB_ID)])

        collect_task = asyncio.create_task(collect())
        await asyncio.sleep(0)
        ctx = JobContext(job_id=_JOB_ID, filename="page.html")
        await node.run(ctx, _reception("text/html"))
        await broadcaster.close(_JOB_ID)
        await collect_task

        assert len(events) == _STARTED_PLUS_OUTCOME_EVENTS
        assert events[0].status == JobStatus.STARTED  # type: ignore[union-attr]
        assert events[1].status == JobStatus.FAILED  # type: ignore[union-attr]

    async def test_audit_records_duration(
        self,
        node: FormatValidationNode,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        ctx = JobContext(job_id=_JOB_ID, filename="sample.pdf")
        await node.run(ctx, _reception("application/pdf"))

        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].duration_ms is not None
        assert records[0].duration_ms >= 0

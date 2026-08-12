import asyncio
from dataclasses import dataclass

import pytest

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.domain.job import JobStatus
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.config_content import ContentValidationConfig
from classiflow.ingesta.domain.context import JobContext
from classiflow.ingesta.domain.results import FileReceptionResult
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.ingesta.nodes.node3_content_validation import ContentValidationNode
from classiflow.ingesta.prompts.content_validation import build_content_chain
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-003"
_STARTED_PLUS_OUTCOME_EVENTS = 2

_SPANISH_TEXT = (
    "El Concejo Municipal de Rosario sanciona la siguiente ordenanza: "
    "Artículo 1º — Apruébase el presupuesto municipal para el ejercicio fiscal correspondiente "
    "al año en curso, conforme al detalle que se adjunta como Anexo I de la presente norma."
)
_SHORT_TEXT = "Short text."  # 11 chars — above ocr_char_threshold (10) but below min_chars (20)
_UNKNOWN_TEXT = "The quick brown fox jumps over the lazy dog. Testing English content here."

_SLM_LEGITIMATE = '{"is_legitimate": true, "confidence": 0.92, "reasoning": "official document"}'
_SLM_NOT_LEGITIMATE = '{"is_legitimate": false, "confidence": 0.85, "reasoning": "spam content"}'
_SLM_LEGITIMATE_LOW_CONFIDENCE = '{"is_legitimate": true, "confidence": 0.5, "reasoning": "unsure"}'

_CONFIG = ContentValidationConfig(
    min_chars=20,
    max_chars=500000,
    ocr_char_threshold=10,
    allowed_languages=["es"],
    slm_confidence_threshold=0.75,
)

_PDF_RECEPTION = FileReceptionResult(
    passed=True,
    sha256="abc123",
    detected_mime="application/pdf",
    file_size_bytes=1024,
)

_DOCX_RECEPTION = FileReceptionResult(
    passed=True,
    sha256="def456",
    detected_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    file_size_bytes=2048,
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
def node(audit: AuditService, broadcaster: EventBroadcaster) -> ContentValidationNode:
    return ContentValidationNode(audit=audit, broadcaster=broadcaster, config=_CONFIG)


@pytest.fixture
def spanish_node(audit: AuditService, broadcaster: EventBroadcaster) -> ContentValidationNode:
    return ContentValidationNode(
        audit=audit,
        broadcaster=broadcaster,
        config=_CONFIG,
        language_detector=_MockDetector("es"),
    )


class TestContentValidationNodeValidate:
    def test_image_only_pdf_sets_requires_ocr(self, node: ContentValidationNode) -> None:
        result = node.validate("", _PDF_RECEPTION)
        assert not result.passed
        assert result.requires_ocr
        assert result.needs_agent_review

    def test_empty_non_pdf_does_not_set_requires_ocr(self, node: ContentValidationNode) -> None:
        result = node.validate("", _DOCX_RECEPTION)
        assert not result.passed
        assert not result.requires_ocr

    def test_text_shorter_than_min_chars_fails(self, node: ContentValidationNode) -> None:
        result = node.validate(_SHORT_TEXT, _PDF_RECEPTION)
        assert not result.passed
        assert not result.requires_ocr
        assert not result.needs_agent_review
        assert "too short" in result.rejection_reason

    def test_char_count_is_recorded(self, node: ContentValidationNode) -> None:
        result = node.validate(_SHORT_TEXT, _PDF_RECEPTION)
        assert result.char_count == len(_SHORT_TEXT)

    def test_non_allowed_language_triggers_review(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
    ) -> None:
        french_node = ContentValidationNode(
            audit=audit,
            broadcaster=broadcaster,
            config=_CONFIG,
            language_detector=_MockDetector("fr"),
        )
        result = french_node.validate(_SPANISH_TEXT, _PDF_RECEPTION)
        assert not result.passed
        assert result.needs_agent_review
        assert result.detected_language == "fr"


class TestContentValidationNodeRun:
    async def test_valid_spanish_passes(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        node = ContentValidationNode(
            audit=audit,
            broadcaster=broadcaster,
            config=_CONFIG,
            language_detector=_MockDetector("es"),
            content_chain=build_content_chain(MockLlm(response=_SLM_LEGITIMATE)),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, _SPANISH_TEXT, _PDF_RECEPTION)

        assert result.passed
        assert result.detected_language == "es"
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == JobStatus.PASSED.value

    async def test_image_only_pdf_routes_to_ocr(
        self,
        node: ContentValidationNode,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        ctx = JobContext(job_id=_JOB_ID, filename="scan.pdf")
        result = await node.run(ctx, "", _PDF_RECEPTION)

        assert not result.passed
        assert result.requires_ocr
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == JobStatus.FAILED.value

    async def test_short_text_fails(
        self,
        node: ContentValidationNode,
    ) -> None:
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, _SHORT_TEXT, _PDF_RECEPTION)

        assert not result.passed
        assert not result.requires_ocr

    async def test_slm_rejects_illegitimate_content(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
    ) -> None:
        node = ContentValidationNode(
            audit=audit,
            broadcaster=broadcaster,
            config=_CONFIG,
            language_detector=_MockDetector("es"),
            content_chain=build_content_chain(MockLlm(response=_SLM_NOT_LEGITIMATE)),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, _SPANISH_TEXT, _PDF_RECEPTION)

        assert not result.passed
        assert result.needs_agent_review
        assert "SLM:" in result.rejection_reason

    async def test_slm_low_confidence_legitimate_triggers_review(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
    ) -> None:
        node = ContentValidationNode(
            audit=audit,
            broadcaster=broadcaster,
            config=_CONFIG,
            language_detector=_MockDetector("es"),
            content_chain=build_content_chain(MockLlm(response=_SLM_LEGITIMATE_LOW_CONFIDENCE)),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, _SPANISH_TEXT, _PDF_RECEPTION)

        assert not result.passed
        assert result.needs_agent_review
        assert "below" in result.rejection_reason

    async def test_emits_started_then_passed(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
    ) -> None:
        node = ContentValidationNode(
            audit=audit,
            broadcaster=broadcaster,
            config=_CONFIG,
            language_detector=_MockDetector("es"),
            content_chain=build_content_chain(MockLlm(response=_SLM_LEGITIMATE)),
        )
        events: list[object] = []

        async def collect() -> None:
            events.extend([event async for event in broadcaster.subscribe(_JOB_ID)])

        collect_task = asyncio.create_task(collect())
        await asyncio.sleep(0)
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        await node.run(ctx, _SPANISH_TEXT, _PDF_RECEPTION)
        await broadcaster.close(_JOB_ID)
        await collect_task

        assert len(events) == _STARTED_PLUS_OUTCOME_EVENTS
        assert events[0].status == JobStatus.STARTED  # type: ignore[union-attr]
        assert events[1].status == JobStatus.PASSED  # type: ignore[union-attr]

    async def test_audit_records_duration(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        audit_repo: InMemoryAuditRepository,
    ) -> None:
        node = ContentValidationNode(
            audit=audit,
            broadcaster=broadcaster,
            config=_CONFIG,
            language_detector=_MockDetector("es"),
            content_chain=build_content_chain(MockLlm(response=_SLM_LEGITIMATE)),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        await node.run(ctx, _SPANISH_TEXT, _PDF_RECEPTION)

        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].duration_ms is not None
        assert records[0].duration_ms >= 0


@dataclass
class _MockIsoCode:
    name: str


@dataclass
class _MockLanguage:
    iso_code_639_1: _MockIsoCode


class _MockDetector:
    """Minimal stand-in for LanguageDetector that returns a fixed language code."""

    def __init__(self, iso_code: str) -> None:
        self._iso_code = iso_code

    def detect_language_of(self, _text: str) -> "_MockLanguage | None":
        return _MockLanguage(_MockIsoCode(self._iso_code))

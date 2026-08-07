from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt
import pytest

from classiflow.ingesta.coordinator import build_coordinator
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.ingesta.nodes.node1_file_reception import FileReceptionNode
from classiflow.ingesta.nodes.node2_format_validation import FormatValidationNode
from classiflow.ingesta.nodes.node3_content_validation import ContentValidationNode
from classiflow.ingesta.nodes.node4_duplicate_control import DuplicateControlNode, EmbeddingStore
from classiflow.shared.audit.service import AuditService
from classiflow.shared.database.repositories.audit import InMemoryAuditRepository
from classiflow.shared.database.repositories.hash import InMemoryHashRepository
from classiflow.shared.events.broadcaster import EventBroadcaster

if TYPE_CHECKING:
    from classiflow.ingesta.domain.state import JobState

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
_SLM_NOT_LEGITIMATE = '{"is_legitimate": false, "confidence": 0.88, "reasoning": "spam"}'

_DIM = 4


def _stub_embed(_text: str) -> npt.NDArray[np.float32]:
    return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


def _make_nodes() -> tuple[
    FileReceptionNode, FormatValidationNode, ContentValidationNode, DuplicateControlNode
]:
    audit = AuditService(InMemoryAuditRepository())
    broadcaster = EventBroadcaster()
    n1 = FileReceptionNode(
        audit=audit,
        broadcaster=broadcaster,
        mime_detector=lambda _b: "application/pdf",
    )
    n2 = FormatValidationNode(audit=audit, broadcaster=broadcaster)
    n3 = ContentValidationNode(
        audit=audit, broadcaster=broadcaster, language_detector=_MockDetector("es")
    )
    n4 = DuplicateControlNode(
        hash_repo=InMemoryHashRepository(),
        audit=audit,
        broadcaster=broadcaster,
        embedding_store=EmbeddingStore(dim=_DIM, embed_fn=_stub_embed),
    )
    return n1, n2, n3, n4


class TestCoordinatorHappyPath:
    async def test_valid_pdf_reaches_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "classiflow.ingesta.nodes.node3_content_validation.get_llm_langchain",
            lambda _path: MockLlm(response=_SLM_LEGITIMATE),
        )

        graph = build_coordinator(*_make_nodes(), text_extractor=lambda _: _SPANISH_TEXT)
        initial: JobState = {
            "job_id": "coord-001",
            "filename": "doc.pdf",
            "file_bytes": _MINIMAL_PDF,
        }
        result = await graph.ainvoke(initial)

        assert result["final_status"] == "accepted"
        assert result["reception"].passed
        assert result["format_validation"].passed
        assert result["content_validation"].passed
        assert result["duplicate_control"].passed

    async def test_second_identical_pdf_is_rejected_as_duplicate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "classiflow.ingesta.nodes.node3_content_validation.get_llm_langchain",
            lambda _path: MockLlm(response=_SLM_LEGITIMATE),
        )

        nodes = _make_nodes()
        graph = build_coordinator(*nodes, text_extractor=lambda _: _SPANISH_TEXT)

        initial: JobState = {
            "job_id": "coord-002a",
            "filename": "doc.pdf",
            "file_bytes": _MINIMAL_PDF,
        }
        await graph.ainvoke(initial)

        initial2: JobState = {
            "job_id": "coord-002b",
            "filename": "doc_copy.pdf",
            "file_bytes": _MINIMAL_PDF,
        }
        result2 = await graph.ainvoke(initial2)

        assert result2["final_status"] == "rejected"
        assert result2["duplicate_control"].is_duplicate


class TestCoordinatorRejectionPaths:
    async def test_empty_file_rejected_at_node1(self) -> None:
        graph = build_coordinator(*_make_nodes(), text_extractor=lambda _: "")
        initial: JobState = {
            "job_id": "coord-003",
            "filename": "empty.pdf",
            "file_bytes": b"",
        }
        result = await graph.ainvoke(initial)

        assert result["final_status"] == "rejected"
        assert not result["reception"].passed
        assert result.get("format_validation") is None

    async def test_missing_file_rejected_at_node1(self) -> None:
        graph = build_coordinator(*_make_nodes(), text_extractor=lambda _: "")
        initial: JobState = {
            "job_id": "coord-004",
            "filename": "none.pdf",
            "file_bytes": None,
        }
        result = await graph.ainvoke(initial)

        assert result["final_status"] == "rejected"
        assert not result["reception"].passed

    async def test_image_only_pdf_rejected_at_node3(self) -> None:
        graph = build_coordinator(*_make_nodes(), text_extractor=lambda _: "")
        initial: JobState = {
            "job_id": "coord-005",
            "filename": "scan.pdf",
            "file_bytes": _MINIMAL_PDF,
        }
        result = await graph.ainvoke(initial)

        assert result["final_status"] == "rejected"
        assert result["content_validation"].requires_ocr

    async def test_non_legitimate_content_goes_to_review(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "classiflow.ingesta.nodes.node3_content_validation.get_llm_langchain",
            lambda _path: MockLlm(response=_SLM_NOT_LEGITIMATE),
        )
        graph = build_coordinator(*_make_nodes(), text_extractor=lambda _: _SPANISH_TEXT)
        initial: JobState = {
            "job_id": "coord-006",
            "filename": "spam.pdf",
            "file_bytes": _MINIMAL_PDF,
        }
        result = await graph.ainvoke(initial)

        assert result["final_status"] == "review"
        assert result["content_validation"].needs_agent_review


# ── helpers ───────────────────────────────────────────────────────────────────


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

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt
from langchain_core.runnables import Runnable
from langgraph.graph.state import CompiledStateGraph

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.database.repositories.hash import InMemoryHashRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.coordinator import build_coordinator
from classiflow.ingesta.domain.results import ExtractionResult
from classiflow.ingesta.extract import TextExtractFn
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.ingesta.nodes.extraction_step import ExtractionStep
from classiflow.ingesta.nodes.node1_file_reception import FileReceptionNode
from classiflow.ingesta.nodes.node2_format_validation import FormatValidationNode
from classiflow.ingesta.nodes.node3_content_validation import ContentValidationNode
from classiflow.ingesta.nodes.node4_duplicate_control import DuplicateControlNode, EmbeddingStore
from classiflow.ingesta.prompts.content_validation import (
    LegitimacyDecisionOutput,
    build_content_chain,
)
from classiflow.services.audit.service import AuditService

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

_SPANISH_EXTRACTION = ExtractionResult(
    text=_SPANISH_TEXT, extractor_used="test", char_count=len(_SPANISH_TEXT)
)
_EMPTY_EXTRACTION = ExtractionResult(text="", extractor_used="", char_count=0)

_DIM = 4


def _stub_embed(_text: str) -> npt.NDArray[np.float32]:
    return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


_CoordinatorNodes = tuple[
    FileReceptionNode,
    FormatValidationNode,
    ExtractionStep,
    ContentValidationNode,
    DuplicateControlNode,
]


def _make_nodes(
    text_extractor: TextExtractFn,
    content_chain: Runnable[dict[str, str], LegitimacyDecisionOutput] | None = None,
) -> _CoordinatorNodes:
    audit = AuditService(InMemoryAuditRepository())
    broadcaster = EventBroadcaster()
    n1 = FileReceptionNode(
        audit=audit,
        broadcaster=broadcaster,
        mime_detector=lambda _b: "application/pdf",
    )
    n2 = FormatValidationNode(audit=audit, broadcaster=broadcaster)
    extraction_step = ExtractionStep(
        audit=audit,
        broadcaster=broadcaster,
        text_extractor=text_extractor,
        semaphore=asyncio.Semaphore(10),
    )
    n3 = ContentValidationNode(
        audit=audit,
        broadcaster=broadcaster,
        language_detector=_MockDetector("es"),
        content_chain=content_chain,
    )
    n4 = DuplicateControlNode(
        hash_repo=InMemoryHashRepository(),
        audit=audit,
        broadcaster=broadcaster,
        embedding_store=EmbeddingStore(dim=_DIM, embed_fn=_stub_embed),
    )
    return n1, n2, extraction_step, n3, n4


def _build_graph(
    text_extractor: TextExtractFn,
    content_chain: Runnable[dict[str, str], LegitimacyDecisionOutput] | None = None,
) -> CompiledStateGraph:
    n1, n2, extraction_step, n3, n4 = _make_nodes(text_extractor, content_chain)
    return build_coordinator(n1, n2, n3, n4, extraction_step=extraction_step)


class TestCoordinatorHappyPath:
    async def test_valid_pdf_reaches_accepted(self) -> None:
        graph = _build_graph(
            lambda *_: _SPANISH_EXTRACTION,
            content_chain=build_content_chain(MockLlm(response=_SLM_LEGITIMATE)),
        )
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

    async def test_second_identical_pdf_is_rejected_as_duplicate(self) -> None:
        graph = _build_graph(
            lambda *_: _SPANISH_EXTRACTION,
            content_chain=build_content_chain(MockLlm(response=_SLM_LEGITIMATE)),
        )

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
        graph = _build_graph(lambda *_: _EMPTY_EXTRACTION)
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
        graph = _build_graph(lambda *_: _EMPTY_EXTRACTION)
        initial: JobState = {
            "job_id": "coord-004",
            "filename": "none.pdf",
            "file_bytes": None,
        }
        result = await graph.ainvoke(initial)

        assert result["final_status"] == "rejected"
        assert not result["reception"].passed

    async def test_image_only_pdf_routed_to_review_at_node3(self) -> None:
        # Extraction (MarkItDown + OCR) already ran inside text_extractor before node3
        # sees the text — an empty result here can't be told apart from an extraction
        # infra failure, so it goes to review for a human, not an automatic reject.
        graph = _build_graph(lambda *_: _EMPTY_EXTRACTION)
        initial: JobState = {
            "job_id": "coord-005",
            "filename": "scan.pdf",
            "file_bytes": _MINIMAL_PDF,
        }
        result = await graph.ainvoke(initial)

        assert result["final_status"] == "review"
        assert result["content_validation"].requires_ocr

    async def test_non_legitimate_content_goes_to_review(self) -> None:
        graph = _build_graph(
            lambda *_: _SPANISH_EXTRACTION,
            content_chain=build_content_chain(MockLlm(response=_SLM_NOT_LEGITIMATE)),
        )
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

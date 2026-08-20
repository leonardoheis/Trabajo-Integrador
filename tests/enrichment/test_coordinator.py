from typing import TYPE_CHECKING

import pytest
from langgraph.graph.state import CompiledStateGraph

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.enrichment.coordinator import build_enrichment_coordinator
from classiflow.enrichment.exceptions import EntityExtractionFailedError
from classiflow.enrichment.nodes import EntityExtractorNode, MetadataEnricherNode, TextCleanerNode
from classiflow.enrichment.prompts.entity_extraction import build_entity_extraction_chain
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.services.audit.service import AuditService

if TYPE_CHECKING:
    from classiflow.enrichment.domain.state import EnrichmentState

_VALID_RESPONSE = (
    '{"doc_type_hint": "ordenanza", "number": "1", "year": 2024, '
    '"issuing_body": "Concejo Municipal", "signatories": [], "article_count": 1}'
)


def _build_graph(entity_response: str) -> CompiledStateGraph:
    audit = AuditService(InMemoryAuditRepository())
    broadcaster = EventBroadcaster()
    text_cleaner = TextCleanerNode(audit=audit, broadcaster=broadcaster)
    entity_extractor = EntityExtractorNode(
        audit=audit,
        broadcaster=broadcaster,
        entity_chain=build_entity_extraction_chain(MockLlm(response=entity_response)),
    )
    metadata_enricher = MetadataEnricherNode(audit=audit, broadcaster=broadcaster)
    return build_enrichment_coordinator(text_cleaner, entity_extractor, metadata_enricher)


class TestEnrichmentCoordinatorHappyPath:
    async def test_full_chain_produces_all_results(self) -> None:
        graph = _build_graph(_VALID_RESPONSE)
        initial: EnrichmentState = {
            "job_id": "enrich-coord-001",
            "filename": "ordenanza.pdf",
            "text": (
                "Municipalidad de Rosario\nArtículo 1º — texto.\n"
                "Municipalidad de Rosario\nMunicipalidad de Rosario"
            ),
            "language": "es",
            "sha256": "a" * 64,
            "stage2_extractor_used": "markitdown",
        }
        result = await graph.ainvoke(initial)

        assert "Artículo 1" in result["cleaned_text"]
        assert result["entities"].doc_type_hint == "ordenanza"
        assert result["metadata"].source == "manual_upload"
        assert result["metadata"].language == "es"
        assert result["metadata"].sha256 == "a" * 64


class TestEnrichmentCoordinatorFailure:
    async def test_entity_extraction_failure_propagates(self) -> None:
        graph = _build_graph("not json")
        initial: EnrichmentState = {
            "job_id": "enrich-coord-002",
            "filename": "doc.pdf",
            "text": "Artículo 1º — texto.",
            "language": "es",
            "sha256": "b" * 64,
            "stage2_extractor_used": "ocr",
        }
        with pytest.raises(EntityExtractionFailedError):
            await graph.ainvoke(initial)

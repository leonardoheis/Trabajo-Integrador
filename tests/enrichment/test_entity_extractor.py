import pytest

from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.enrichment.exceptions import EntityExtractionFailedError
from classiflow.enrichment.nodes.entity_extractor import EntityExtractorNode
from classiflow.enrichment.prompts.entity_extraction import build_entity_extraction_chain
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-enrich-001"
_EXPECTED_YEAR = 2020
_EXPECTED_ARTICLE_COUNT = 1
_VALID_RESPONSE = (
    '{"doc_type_hint": "decreto", "number": "42", "year": 2020, '
    '"issuing_body": "Intendencia", "signatories": [], "article_count": 1}'
)


def _node(response: str) -> EntityExtractorNode:
    return EntityExtractorNode(
        audit=AuditService(InMemoryAuditRepository()),
        broadcaster=EventBroadcaster(),
        entity_chain=build_entity_extraction_chain(MockLlm(response=response)),
    )


class TestEntityExtractorExtract:
    def test_extract_returns_result_on_valid_response(self) -> None:
        result = _node(_VALID_RESPONSE).extract("Artículo 1º ...")
        assert result.doc_type_hint == "decreto"
        assert result.number == "42"
        assert result.year == _EXPECTED_YEAR

    def test_extract_raises_domain_error_on_malformed_response(self) -> None:
        with pytest.raises(EntityExtractionFailedError, match="No valid JSON object"):
            _node("not json").extract("Artículo 1º ...")


class TestEntityExtractorRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = EntityExtractorNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            entity_chain=build_entity_extraction_chain(MockLlm(response=_VALID_RESPONSE)),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, "Artículo 1º ...")
        assert result.doc_type_hint == "decreto"
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"

    async def test_run_emits_failed_and_reraises_on_error(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = EntityExtractorNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            entity_chain=build_entity_extraction_chain(MockLlm(response="not json")),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        with pytest.raises(EntityExtractionFailedError):
            await node.run(ctx, "Artículo 1º ...")
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "failed"

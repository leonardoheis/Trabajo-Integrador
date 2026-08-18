from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.enrichment.nodes.metadata_enricher import MetadataEnricherNode
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-enrich-002"


class TestMetadataEnricherRun:
    async def test_attaches_expected_fields(self) -> None:
        node = MetadataEnricherNode(
            audit=AuditService(InMemoryAuditRepository()), broadcaster=EventBroadcaster()
        )
        ctx = JobContext(job_id=_JOB_ID, filename="ordenanza.pdf")
        result = await node.run(
            ctx,
            filename="ordenanza.pdf",
            language="es",
            sha256="a" * 64,
            stage2_extractor_used="markitdown",
        )
        assert result.source == "manual_upload"
        assert result.filename == "ordenanza.pdf"
        assert result.language == "es"
        assert result.sha256 == "a" * 64
        assert result.stage2_extractor_used == "markitdown"

    async def test_emits_started_then_passed(self) -> None:
        audit_repo = InMemoryAuditRepository()
        node = MetadataEnricherNode(audit=AuditService(audit_repo), broadcaster=EventBroadcaster())
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        await node.run(
            ctx, filename="doc.pdf", language="es", sha256="b" * 64, stage2_extractor_used="ocr"
        )
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"

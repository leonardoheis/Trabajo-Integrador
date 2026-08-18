from classiflow.database.repositories.audit import AuditDetail
from classiflow.enrichment.domain.results import MetadataEnrichmentResult
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext

_SOURCE = "manual_upload"


class MetadataEnricherNode(BaseNode):
    @property
    def name(self) -> str:
        return "enrichment_metadata_enricher"

    async def run(
        self,
        ctx: JobContext,
        *,
        filename: str,
        language: str,
        sha256: str,
        stage2_extractor_used: str,
    ) -> MetadataEnrichmentResult:
        start = await self._emit_started(ctx)
        result = MetadataEnrichmentResult(
            source=_SOURCE,
            filename=filename,
            language=language,
            sha256=sha256,
            stage2_extractor_used=stage2_extractor_used,
        )
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({"filename": filename, "source": _SOURCE}),
        )
        return result

import asyncio

from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.domain import ExtractionResult, JobContext
from classiflow.ingesta.extract import TextExtractFn
from classiflow.ingesta.nodes.base import BaseNode
from classiflow.services.audit.service import AuditService


class ExtractionStep(BaseNode):
    @property
    def name(self) -> str:
        return "extraction"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        text_extractor: TextExtractFn,
        *,
        semaphore: asyncio.Semaphore,
    ) -> None:
        super().__init__(audit, broadcaster)
        self._text_extractor = text_extractor
        self._semaphore = semaphore

    async def run(self, ctx: JobContext, file_bytes: bytes, filename: str) -> ExtractionResult:
        start = await self._emit_started(ctx)
        # Bounds how many extractions (MarkItDown/OCR calls) run concurrently across all
        # in-flight /pipeline/ingest requests, not just within one -- Container-managed
        # (see injections/production.py's `extraction_semaphore`), process-wide-lived,
        # same category as `broadcaster`.
        async with self._semaphore:
            result = await asyncio.to_thread(self._text_extractor, file_bytes, filename)
        # Deliberately lean, matching node1-4's own audit detail -- full text belongs in
        # DocumentStep (via PipelineService._persist_steps' generic result.model_dump()
        # on state["extraction"]), not duplicated into every real-time AuditRecord too.
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": filename,
                "extractor_used": result.extractor_used,
                "char_count": result.char_count,
            }),
        )
        return result

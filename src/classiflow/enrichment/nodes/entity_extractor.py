import asyncio
from typing import Protocol, cast, runtime_checkable

from classiflow.database.repositories.audit import AuditDetail
from classiflow.enrichment.config_enrichment import EnrichmentConfig, get_enrichment_config
from classiflow.enrichment.domain.results import EntityExtractionResult
from classiflow.enrichment.exceptions import EntityExtractionFailedError
from classiflow.enrichment.prompts.entity_extraction import (
    EntityExtractionInput,
    EntityExtractionOutput,
    build_entity_extraction_chain,
)
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.exceptions import LlmProviderError
from classiflow.ingesta.llm_provider import get_llm_langchain
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService
from classiflow.settings import Settings


@runtime_checkable
class EntityChain(Protocol):
    def invoke(self, inp: EntityExtractionInput, **kwargs: object) -> EntityExtractionOutput: ...


class EntityExtractorNode(BaseNode):
    @property
    def name(self) -> str:
        return "enrichment_entity_extractor"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        entity_chain: EntityChain | None = None,
        config: EnrichmentConfig | None = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.entity_chain: EntityChain | None = entity_chain
        self.config: EnrichmentConfig = config if config is not None else get_enrichment_config()

    async def run(self, ctx: JobContext, cleaned_text: str) -> EntityExtractionResult:
        start = await self._emit_started(ctx)
        try:
            result = await asyncio.to_thread(self.extract, cleaned_text)
        except EntityExtractionFailedError as exc:
            await self._emit_and_audit(
                ctx,
                start,
                passed=False,
                detail=AuditDetail.model_validate({"filename": ctx.filename, "error": str(exc)}),
            )
            raise
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "doc_type_hint": result.doc_type_hint,
                "article_count": result.article_count,
            }),
        )
        return result

    def _resolve_chain(self) -> EntityChain:
        # Deliberately does NOT drop self.entity_chain after use, unlike
        # node2/node3/primary_classifier: PipelineService._run_enrichment retries the
        # whole enrichment coordinator up to max_enrichment_retries times against this
        # same node instance, so releasing the injected chain would silently swap in a
        # freshly built one on retry 2.
        if self.entity_chain is not None:
            return self.entity_chain
        return cast(
            "EntityChain",
            build_entity_extraction_chain(get_llm_langchain(Settings.enrichment_model_path)),
        )

    def extract(self, cleaned_text: str) -> EntityExtractionResult:
        excerpt = cleaned_text[: self.config.entity_excerpt_len]
        try:
            chain = self._resolve_chain()
            output = chain.invoke(EntityExtractionInput(cleaned_text=excerpt))
        except (ValueError, LlmProviderError, OSError, RuntimeError) as exc:
            raise EntityExtractionFailedError(reason=str(exc)) from exc
        return EntityExtractionResult(
            doc_type_hint=output.doc_type_hint,
            number=output.number,
            year=output.year,
            issuing_body=output.issuing_body,
            signatories=output.signatories,
            article_count=output.article_count,
        )

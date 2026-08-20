import asyncio
from typing import Protocol, cast, runtime_checkable

from classiflow.classification.config_classification import (
    ClassificationConfig,
    get_classification_config,
)
from classiflow.classification.domain.results import PrimaryClassificationOutput
from classiflow.classification.exceptions import PrimaryClassificationFailedError
from classiflow.classification.prompts.primary_classification import (
    PrimaryClassificationInput,
    build_classification_chain,
)
from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.exceptions import LlmProviderError
from classiflow.ingesta.llm_provider import get_llm_langchain
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService
from classiflow.settings import Settings


@runtime_checkable
class _ClassificationChain(Protocol):
    def invoke(
        self, inp: PrimaryClassificationInput, **kwargs: object
    ) -> PrimaryClassificationOutput: ...


class PrimaryClassifierNode(BaseNode):
    @property
    def name(self) -> str:
        return "classification_primary_classifier"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        classification_chain: _ClassificationChain | None = None,
        config: ClassificationConfig | None = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.classification_chain: _ClassificationChain | None = classification_chain
        self.config: ClassificationConfig = (
            config if config is not None else get_classification_config()
        )

    async def run(self, ctx: JobContext, cleaned_text: str) -> PrimaryClassificationOutput:
        start = await self._emit_started(ctx)
        try:
            result = await asyncio.to_thread(self.classify, cleaned_text)
        except PrimaryClassificationFailedError as exc:
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
                "label": result.label,
                "confidence": result.confidence,
            }),
        )
        return result

    def classify(self, cleaned_text: str) -> PrimaryClassificationOutput:
        excerpt = cleaned_text[: self.config.max_input_tokens]
        try:
            if self.classification_chain is not None:
                chain: _ClassificationChain = self.classification_chain
            else:
                chain = cast(
                    "_ClassificationChain",
                    build_classification_chain(
                        get_llm_langchain(Settings.classification_model_path)
                    ),
                )
            return chain.invoke(PrimaryClassificationInput(cleaned_text=excerpt))
        except (ValueError, LlmProviderError, OSError, RuntimeError) as exc:
            raise PrimaryClassificationFailedError(reason=str(exc)) from exc

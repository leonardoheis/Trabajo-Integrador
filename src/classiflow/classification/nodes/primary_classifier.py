import asyncio
import time
from typing import Protocol, cast, runtime_checkable

import torch
from loguru import logger

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

    def _resolve_chain(self) -> _ClassificationChain:
        if self.classification_chain is not None:
            chain = self.classification_chain
            # Drop this node's own reference to the injected chain (and the GGUF
            # model it wraps) once used -- this node runs exactly once per job, so
            # nothing else needs it after this call, but the chain would otherwise
            # stay reachable through PipelineService's classification_coordinator
            # closure for the job's full remaining duration, blocking
            # get_llm_langchain's unload_slm() from ever actually freeing that
            # model's VRAM before a later stage (e.g. the LLM Judge) tries to load
            # a different one.
            self.classification_chain = None
            return chain
        return cast(
            "_ClassificationChain",
            build_classification_chain(get_llm_langchain(Settings.classification_model_path)),
        )

    @staticmethod
    def _invoke_with_probe(
        chain: _ClassificationChain, excerpt: str
    ) -> PrimaryClassificationOutput:
        # ponytail: temporary probe to tell apart "prompt eval is just slow" from
        # "llama.cpp is spilling to CPU because VRAM is nearly full" -- remove once
        # the classifier's real latency source (Stage 4 follow-up) is confirmed.
        if torch.cuda.is_available():
            free_b, total_b = torch.cuda.mem_get_info()
            logger.info(
                "[classifier probe] VRAM free={:.2f}GB/{:.2f}GB before call",
                free_b / 2**30,
                total_b / 2**30,
            )
        call_start = time.monotonic()
        result = chain.invoke(PrimaryClassificationInput(cleaned_text=excerpt))
        elapsed = time.monotonic() - call_start
        logger.info("[classifier probe] excerpt_chars={} elapsed={:.1f}s", len(excerpt), elapsed)
        return result

    def classify(self, cleaned_text: str) -> PrimaryClassificationOutput:
        excerpt = cleaned_text[: self.config.max_input_tokens]
        try:
            chain = self._resolve_chain()
            return self._invoke_with_probe(chain, excerpt)
        except (ValueError, LlmProviderError, OSError, RuntimeError) as exc:
            raise PrimaryClassificationFailedError(reason=str(exc)) from exc

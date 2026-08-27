import asyncio
from typing import Protocol, cast, runtime_checkable

from classiflow.classification.config_classification import (
    ClassificationConfig,
    get_classification_config,
)
from classiflow.classification.domain.results import JudgeOutput
from classiflow.classification.exceptions import LlmJudgeFailedError
from classiflow.classification.prompts.llm_judge import JudgeInput, build_judge_chain
from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.exceptions import LlmProviderError
from classiflow.ingesta.llm_provider import get_llm_langchain, unload_slm
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService
from classiflow.settings import Settings


@runtime_checkable
class _JudgeChain(Protocol):
    def invoke(self, inp: JudgeInput, **kwargs: object) -> JudgeOutput: ...


class LlmJudgeNode(BaseNode):
    @property
    def name(self) -> str:
        return "classification_llm_judge"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        judge_chain: _JudgeChain | None = None,
        config: ClassificationConfig | None = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.judge_chain: _JudgeChain | None = judge_chain
        self.config: ClassificationConfig = (
            config if config is not None else get_classification_config()
        )

    async def run(self, ctx: JobContext, judge_input: JudgeInput) -> JudgeOutput:
        start = await self._emit_started(ctx)
        truncated_text = judge_input.cleaned_text[: self.config.judge_max_input_chars]
        if truncated_text != judge_input.cleaned_text:
            judge_input = judge_input.model_copy(update={"cleaned_text": truncated_text})
        try:
            result = await asyncio.to_thread(self.judge, judge_input)
        except LlmJudgeFailedError as exc:
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
                "accept": result.accept,
                "reasoning": result.reasoning,
            }),
        )
        return result

    def _take_chain(self) -> "_JudgeChain":
        # Hands over the injected chain and drops this node's reference (one call per
        # job), same as the other chain-holding nodes; the judge's model is the largest,
        # so pinning it past this call is the most expensive case.
        if self.judge_chain is not None:
            chain = self.judge_chain
            self.judge_chain = None
            return chain
        # By the time a job reaches the judge tier, node2/node3/enrichment's and the
        # primary classifier's chain-holding nodes have each already dropped their own
        # reference to their GGUF model after their one use per job -- so the only thing
        # still keeping those models resident in VRAM is get_llm_langchain's own
        # lru_cache. Clearing it here, right before the judge's own (typically larger)
        # model loads, actually frees that VRAM instead of stacking multiple GGUF models
        # at once on a small/mid-range GPU.
        unload_slm()
        return cast("_JudgeChain", build_judge_chain(get_llm_langchain(Settings.judge_model_path)))

    def judge(self, judge_input: JudgeInput) -> JudgeOutput:
        try:
            chain = self._take_chain()
            return chain.invoke(judge_input)
        except (ValueError, LlmProviderError, OSError, RuntimeError) as exc:
            raise LlmJudgeFailedError(reason=str(exc)) from exc

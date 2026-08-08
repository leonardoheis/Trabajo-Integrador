from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.config import AllowedFormatsConfig, get_allowed_formats
from classiflow.ingesta.domain.context import JobContext
from classiflow.ingesta.domain.results import (
    FileReceptionResult,
    FormatDecision,
    FormatValidationResult,
)
from classiflow.ingesta.llm_provider import get_llm_langchain
from classiflow.ingesta.nodes.base import BaseNode
from classiflow.ingesta.prompts.format_validation import FormatDecisionOutput, build_format_chain
from classiflow.services.audit.service import AuditService
from classiflow.settings import Settings


@runtime_checkable
class _FormatChain(Protocol):
    def invoke(self, inp: dict[str, str], **kwargs: object) -> FormatDecisionOutput: ...


class FormatValidationNode(BaseNode):
    @property
    def name(self) -> str:
        return "node2_format_validation"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        config: AllowedFormatsConfig | None = None,
        format_chain: "_FormatChain | None" = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.config: AllowedFormatsConfig = config if config is not None else get_allowed_formats()
        self.format_chain: _FormatChain | None = format_chain

    async def run(self, ctx: JobContext, reception: FileReceptionResult) -> FormatValidationResult:
        start = await self._emit_started(ctx)
        result = self._validate(ctx.filename, reception)
        await self._emit_and_audit(
            ctx,
            start,
            passed=result.passed,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "detected_mime": reception.detected_mime,
                "decision": result.decision.value,
                "used_slm": result.used_slm,
                "passed": result.passed,
                "rejection_reason": result.rejection_reason,
            }),
        )
        return result

    def _validate(self, filename: str, reception: FileReceptionResult) -> FormatValidationResult:
        decision = self._rule_based_check(filename, reception.detected_mime)

        if decision is None:
            return self._slm_check(filename, reception)

        if decision == FormatDecision.ACCEPT:
            return FormatValidationResult(passed=True, decision=decision)

        if decision == FormatDecision.REJECT:
            return FormatValidationResult(
                passed=False,
                decision=decision,
                rejection_reason=f"File format rejected: {reception.detected_mime}",
            )

        return FormatValidationResult(
            passed=False,
            decision=decision,
            rejection_reason=(
                f"Unknown MIME type, requires manual review: {reception.detected_mime}"
            ),
        )

    def _rule_based_check(self, filename: str, detected_mime: str) -> FormatDecision | None:
        extension = Path(filename).suffix.lower()

        if (
            detected_mime in self.config.disabled_mime_types
            or extension in self.config.disabled_extensions
        ):
            return FormatDecision.REJECT

        if detected_mime not in self.config.allowed_mime_types:
            if extension in self.config.known_mismatches.get(detected_mime, []):
                return FormatDecision.ACCEPT
            return FormatDecision.MANUAL_REVIEW

        expected_extensions = self.config.mime_to_extensions.get(detected_mime, [])
        if expected_extensions and extension not in expected_extensions:
            return None  # gray zone: MIME/extension mismatch → SLM escalation

        return FormatDecision.ACCEPT

    def _slm_check(self, filename: str, reception: FileReceptionResult) -> FormatValidationResult:
        if self.format_chain is not None:
            chain: _FormatChain = self.format_chain
        else:
            chain = cast(
                "_FormatChain",
                build_format_chain(get_llm_langchain(Settings.node2_model_path)),
            )
        output: FormatDecisionOutput = chain.invoke({
            "filename": filename,
            "detected_mime": reception.detected_mime,
        })
        passed = output.decision == FormatDecision.ACCEPT
        return FormatValidationResult(
            passed=passed,
            decision=output.decision,
            used_slm=True,
            rejection_reason="" if passed else f"SLM: {output.reasoning}",
        )

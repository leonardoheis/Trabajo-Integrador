import time
from pathlib import Path

from pydantic import ConfigDict, Field

from classiflow.ingesta.config import AllowedFormatsConfig, get_allowed_formats
from classiflow.ingesta.domain.results import (
    FileReceptionResult,
    FormatDecision,
    FormatValidationResult,
)
from classiflow.ingesta.llm_provider import get_llm_langchain
from classiflow.ingesta.nodes.base import BaseNode
from classiflow.ingesta.prompts.format_validation import FormatDecisionOutput, build_format_chain
from classiflow.settings import Settings
from classiflow.shared.audit.service import AuditService
from classiflow.shared.database.repositories.audit import AuditDetail
from classiflow.shared.domain.job import JobStatus, NodeEvent
from classiflow.shared.events.broadcaster import EventBroadcaster


class FormatValidationNode(BaseNode):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def name(self) -> str:
        return "node2_format_validation"

    @property
    def model_path(self) -> str:
        return Settings.node2_model_path

    audit: AuditService
    broadcaster: EventBroadcaster
    config: AllowedFormatsConfig = Field(default_factory=get_allowed_formats)

    async def run(
        self,
        job_id: str,
        filename: str,
        reception: FileReceptionResult,
    ) -> FormatValidationResult:
        start = time.monotonic()

        await self.broadcaster.emit(
            NodeEvent(job_id=job_id, node=self.name, status=JobStatus.STARTED)
        )

        result = self._validate(filename, reception)
        duration_ms = int((time.monotonic() - start) * 1000)

        status = JobStatus.PASSED if result.passed else JobStatus.FAILED
        await self.broadcaster.emit(NodeEvent(job_id=job_id, node=self.name, status=status))

        await self.audit.record(
            job_id,
            self.name,
            status.value,
            duration_ms=duration_ms,
            detail=AuditDetail.model_validate({
                "filename": filename,
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
        llm = get_llm_langchain(self.model_path)
        output: FormatDecisionOutput = build_format_chain(llm).invoke({
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

from functools import lru_cache
from typing import Protocol, cast, runtime_checkable

from lingua import LanguageDetector, LanguageDetectorBuilder
from pydantic import Field

from classiflow.database.repositories.audit import AuditDetail
from classiflow.ingesta.config_content import ContentValidationConfig, get_content_validation_config
from classiflow.ingesta.domain.context import JobContext
from classiflow.ingesta.domain.results import ContentValidationResult, FileReceptionResult
from classiflow.ingesta.llm_provider import get_llm_langchain
from classiflow.ingesta.nodes.base import BaseNode
from classiflow.ingesta.prompts.content_validation import (
    LegitimacyDecisionOutput,
    build_content_chain,
)
from classiflow.settings import Settings

_PDF_MIME = "application/pdf"


class _IsoCode(Protocol):
    @property
    def name(self) -> str: ...


class _Language(Protocol):
    @property
    def iso_code_639_1(self) -> _IsoCode: ...


@runtime_checkable
class _LanguageDetector(Protocol):
    def detect_language_of(self, text: str) -> _Language | None: ...


@runtime_checkable
class _ContentChain(Protocol):
    def invoke(self, inp: dict[str, str], **kwargs: object) -> LegitimacyDecisionOutput: ...


@lru_cache(maxsize=1)
def _get_detector() -> LanguageDetector:
    return LanguageDetectorBuilder.from_all_languages().build()


class ContentValidationNode(BaseNode):
    @property
    def name(self) -> str:
        return "node3_content_validation"

    config: ContentValidationConfig = Field(default_factory=get_content_validation_config)
    language_detector: _LanguageDetector = Field(default_factory=_get_detector)
    content_chain: _ContentChain | None = None

    async def run(
        self,
        ctx: JobContext,
        text: str,
        reception: FileReceptionResult,
    ) -> ContentValidationResult:
        start = await self._emit_started(ctx)
        result = self._validate(text, reception)
        await self._emit_and_audit(
            ctx,
            start,
            passed=result.passed,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "char_count": result.char_count,
                "detected_language": result.detected_language,
                "requires_ocr": result.requires_ocr,
                "needs_agent_review": result.needs_agent_review,
                "passed": result.passed,
                "rejection_reason": result.rejection_reason,
            }),
        )
        return result

    def _validate(self, text: str, reception: FileReceptionResult) -> ContentValidationResult:
        char_count = len(text)

        if char_count < self.config.ocr_char_threshold and reception.detected_mime == _PDF_MIME:
            return ContentValidationResult(
                passed=False,
                char_count=char_count,
                requires_ocr=True,
                rejection_reason="Image-only PDF: routed to OCR pipeline",
            )

        if char_count < self.config.min_chars:
            reason = f"Text too short: {char_count} chars (min {self.config.min_chars})"
            return ContentValidationResult(
                passed=False, char_count=char_count, rejection_reason=reason
            )

        detected_language = self._detect_language(text)

        if detected_language not in self.config.allowed_languages:
            return ContentValidationResult(
                passed=False,
                char_count=char_count,
                detected_language=detected_language,
                needs_agent_review=True,
                rejection_reason=f"Language not allowed: {detected_language}",
            )

        return self._slm_legitimacy_check(text, detected_language, char_count)

    def _detect_language(self, text: str) -> str:
        language = self.language_detector.detect_language_of(text[: self.config.excerpt_len])
        if language is None:
            return "unknown"
        return language.iso_code_639_1.name.lower()

    def _slm_legitimacy_check(
        self, text: str, detected_language: str, char_count: int
    ) -> ContentValidationResult:
        if self.content_chain is not None:
            chain: _ContentChain = self.content_chain
        else:
            chain = cast(
                "_ContentChain",
                build_content_chain(get_llm_langchain(Settings.node3_model_path)),
            )
        output: LegitimacyDecisionOutput = chain.invoke({
            "text_excerpt": text[: self.config.excerpt_len],
            "detected_language": detected_language,
        })
        if output.is_legitimate:
            return ContentValidationResult(
                passed=True,
                char_count=char_count,
                detected_language=detected_language,
            )
        return ContentValidationResult(
            passed=False,
            char_count=char_count,
            detected_language=detected_language,
            needs_agent_review=True,
            rejection_reason=f"SLM: {output.reasoning}",
        )

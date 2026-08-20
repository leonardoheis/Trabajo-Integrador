import asyncio
from functools import lru_cache
from typing import Protocol, cast, runtime_checkable

from lingua import LanguageDetector, LanguageDetectorBuilder

from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.config_content import ContentValidationConfig, get_content_validation_config
from classiflow.ingesta.domain import ContentValidationResult, FileReceptionResult, JobContext
from classiflow.ingesta.llm_provider import get_llm_langchain
from classiflow.ingesta.prompts import (
    ContentChainInput,
    LegitimacyDecisionOutput,
    build_content_chain,
)
from classiflow.pipeline.base import BaseNode
from classiflow.services.audit.service import AuditService
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
    def invoke(self, inp: ContentChainInput, **kwargs: object) -> LegitimacyDecisionOutput: ...


@lru_cache(maxsize=1)
def get_language_detector() -> LanguageDetector:
    # Kept cached even though Container.language_detector (injections/production.py)
    # already gives production a single shared instance via constructor injection --
    # this function is also the fallback ContentValidationNode.__init__ reaches for
    # when no language_detector is passed, which still happens for
    # TestContainer.node3 (a Factory -- fresh ContentValidationNode, and thus this
    # fallback, on every resolution). Without the cache, every such test would rebuild
    # Lingua's full multi-language n-gram model from scratch. Same reasoning as
    # get_llm_langchain's cache, which unload_slm() also depends on staying in place.
    return LanguageDetectorBuilder.from_all_languages().build()


class ContentValidationNode(BaseNode):
    @property
    def name(self) -> str:
        return "node3_content_validation"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        config: ContentValidationConfig | None = None,
        language_detector: "_LanguageDetector | None" = None,
        content_chain: "_ContentChain | None" = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.config: ContentValidationConfig = (
            config if config is not None else get_content_validation_config()
        )
        self.language_detector: _LanguageDetector = (
            language_detector if language_detector is not None else get_language_detector()
        )
        self.content_chain: _ContentChain | None = content_chain

    async def run(
        self,
        ctx: JobContext,
        text: str,
        reception: FileReceptionResult,
    ) -> ContentValidationResult:
        start = await self._emit_started(ctx)
        # validate() may call the SLM chain synchronously — see BaseNode's note above.
        result = await asyncio.to_thread(self.validate, text, reception)
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

    def validate(self, text: str, reception: FileReceptionResult) -> ContentValidationResult:
        char_count = len(text)

        if char_count < self.config.ocr_char_threshold and reception.detected_mime == _PDF_MIME:
            # Text extraction (MarkItDown + OCR fallback) already ran before this node
            # saw the text — coming up empty here means either a genuinely blank scan
            # or an extraction-infrastructure failure (e.g. an OCR engine crash), and
            # this node can't tell those apart. Route to review instead of auto-reject
            # so a human decides, rather than silently discarding a possibly-valid
            # document over a tooling failure that wasn't its fault.
            return ContentValidationResult(
                passed=False,
                char_count=char_count,
                requires_ocr=True,
                needs_agent_review=True,
                rejection_reason="PDF has no extractable text after OCR — needs human review",
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
        try:
            output: LegitimacyDecisionOutput = chain.invoke(
                ContentChainInput(
                    text_excerpt=text[: self.config.excerpt_len],
                    detected_language=detected_language,
                )
            )
        except ValueError as exc:
            # A local quantized model can produce output no amount of prompt-tuning
            # fully rules out (missing fields, unescaped quotes breaking JSON). That's
            # infrastructure flakiness, not evidence the document is illegitimate --
            # route to review instead of letting it crash the whole ingest request.
            return ContentValidationResult(
                passed=False,
                char_count=char_count,
                detected_language=detected_language,
                needs_agent_review=True,
                rejection_reason=f"SLM response could not be parsed: {exc}",
            )
        low_confidence = output.confidence < self.config.slm_confidence_threshold
        if output.is_legitimate and not low_confidence:
            return ContentValidationResult(
                passed=True,
                char_count=char_count,
                detected_language=detected_language,
                confidence=output.confidence,
            )
        reason = f"SLM: {output.reasoning}"
        if low_confidence:
            reason = (
                f"{reason} (confidence {output.confidence:.2f} below "
                f"{self.config.slm_confidence_threshold:.2f} threshold)"
            )
        return ContentValidationResult(
            passed=False,
            char_count=char_count,
            detected_language=detected_language,
            confidence=output.confidence,
            needs_agent_review=True,
            rejection_reason=reason,
        )

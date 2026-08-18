import re
import unicodedata

from classiflow.database.repositories.audit import AuditDetail
from classiflow.enrichment.config_enrichment import EnrichmentConfig, get_enrichment_config
from classiflow.enrichment.domain.results import TextCleaningResult
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_PAGE_NUMBER_RE = re.compile(r"^(p[aá]gina\s+)?\d+(\s*/\s*\d+)?$", re.IGNORECASE)
# Strips characters that aren't letters (incl. accented Spanish), digits, whitespace,
# or common punctuation seen in municipal act text -- OCR noise typically shows up as
# runs of symbols outside this set.
_NOISE_RE = re.compile(r"[^\w\sáéíóúñÁÉÍÓÚÑüÜ.,;:()\-\"'ºª/%]")


class TextCleanerNode(BaseNode):
    @property
    def name(self) -> str:
        return "enrichment_text_cleaner"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        config: EnrichmentConfig | None = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.config: EnrichmentConfig = config if config is not None else get_enrichment_config()

    async def run(self, ctx: JobContext, text: str) -> TextCleaningResult:
        start = await self._emit_started(ctx)
        result = self.clean(text)
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "input_chars": len(text),
                "output_chars": len(result.cleaned_text),
            }),
        )
        return result

    def clean(self, text: str) -> TextCleaningResult:
        # Normalize to NFC first so combining diacritics become precomposed chars
        # and won't be stripped by the noise regex
        text = unicodedata.normalize("NFC", text)

        lines = text.split("\n")
        counts: dict[str, int] = {}
        for line in lines:
            stripped = line.strip()
            if stripped:
                counts[stripped] = counts.get(stripped, 0) + 1

        kept: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if counts[stripped] >= self.config.repeated_line_min_count:
                continue
            if _PAGE_NUMBER_RE.match(stripped):
                continue
            kept.append(_NOISE_RE.sub("", stripped))

        return TextCleaningResult(cleaned_text="\n".join(kept))

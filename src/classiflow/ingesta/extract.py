from collections.abc import Callable

from loguru import logger

from classiflow.ingesta.config_extraction import ExtractionConfig, get_extraction_config
from classiflow.ingesta.domain.results import ExtractionResult
from classiflow.ingesta.extractors import ExtractionError, ExtractorBase

# Lives here, not in coordinator.py, so nodes/extraction_step.py (which needs it too)
# doesn't have to import from coordinator.py -- coordinator.py already imports the
# nodes, so the reverse import would be circular.
TextExtractFn = Callable[[bytes, str], ExtractionResult]


class TextExtractor:
    def __init__(self, chain: list[ExtractorBase], config: ExtractionConfig | None = None) -> None:
        self._chain = chain
        self.config: ExtractionConfig = config if config is not None else get_extraction_config()

    def __call__(self, file_bytes: bytes, filename: str) -> ExtractionResult:
        text = ""
        extractor_used = ""
        for extractor in self._chain:
            if len(text) >= self.config.min_text_for_ocr:
                break
            try:
                text = extractor.extract(file_bytes, filename)
                extractor_used = extractor.name
            except ExtractionError as exc:
                logger.warning(str(exc))

        # char_count/extractor_used stay informative even when the text itself is
        # unusable (Stage 2's observability work reads these) -- only the text a
        # caller actually receives is zeroed out below min_usable_text.
        usable_text = text if len(text) >= self.config.min_usable_text else ""
        return ExtractionResult(
            text=usable_text, extractor_used=extractor_used, char_count=len(text)
        )

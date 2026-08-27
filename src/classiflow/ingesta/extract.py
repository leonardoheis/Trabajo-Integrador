from collections.abc import Callable

import pymupdf
from loguru import logger

from classiflow.ingesta.config_extraction import ExtractionConfig, get_extraction_config
from classiflow.ingesta.domain import ExtractionResult
from classiflow.ingesta.extractors import ExtractionError, ExtractorBase

# Lives here, not in coordinator.py, so nodes/extraction_step.py (which needs it too)
# doesn't have to import from coordinator.py -- coordinator.py already imports the
# nodes, so the reverse import would be circular.
TextExtractFn = Callable[[bytes, str], ExtractionResult]


class TextExtractor:
    def __init__(self, chain: list[ExtractorBase], config: ExtractionConfig | None = None) -> None:
        self._chain = chain
        self.config: ExtractionConfig = config if config is not None else get_extraction_config()

    def _has_unextracted_scanned_page(self, file_bytes: bytes) -> bool:
        # A page carrying an image but (almost) no text layer is a scan the text-layer
        # extractor cannot see -- a document-total char count misses it whenever one
        # other page contributes enough text (e.g. a 3-page scan whose only text layer
        # is scanner-baked OCR junk on the last page).
        try:
            with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
                return any(
                    page.get_images()
                    and len(page.get_text().strip()) < self.config.ocr_page_min_chars
                    for page in doc
                )
        except pymupdf.FileDataError:
            return False  # not a PDF -- the total-char-count rule alone applies

    def __call__(self, file_bytes: bytes, filename: str) -> ExtractionResult:
        text = ""
        extractor_used = ""
        force_ocr = self._has_unextracted_scanned_page(file_bytes)
        for extractor in self._chain:
            if len(text) >= self.config.min_text_for_ocr and not force_ocr:
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

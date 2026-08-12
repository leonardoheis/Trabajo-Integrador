from loguru import logger

from classiflow.ingesta.extractors import (
    ExtractionError,
    ExtractorBase,
    MarkItDownExtractor,
    OCRExtractor,
)

MIN_TEXT_FOR_OCR = 50
MIN_USABLE_TEXT = 20

_DEFAULT_CHAIN: list[ExtractorBase] = [MarkItDownExtractor(), OCRExtractor()]


def extract_document(
    file_bytes: bytes, filename: str, *, chain: list[ExtractorBase] | None = None
) -> str:
    active_chain = chain if chain is not None else _DEFAULT_CHAIN
    text = ""
    for extractor in active_chain:
        if len(text) >= MIN_TEXT_FOR_OCR:
            break
        try:
            text = extractor.extract(file_bytes, filename)
        except ExtractionError as exc:
            logger.warning(str(exc))

    return text if len(text) >= MIN_USABLE_TEXT else ""

from loguru import logger

from classiflow.ingesta.extractors import ExtractionError, ExtractorBase

MIN_TEXT_FOR_OCR = 50
MIN_USABLE_TEXT = 20


class TextExtractor:
    def __init__(self, chain: list[ExtractorBase]) -> None:
        self._chain = chain

    def __call__(self, file_bytes: bytes, filename: str) -> str:
        text = ""
        for extractor in self._chain:
            if len(text) >= MIN_TEXT_FOR_OCR:
                break
            try:
                text = extractor.extract(file_bytes, filename)
            except ExtractionError as exc:
                logger.warning(str(exc))

        return text if len(text) >= MIN_USABLE_TEXT else ""

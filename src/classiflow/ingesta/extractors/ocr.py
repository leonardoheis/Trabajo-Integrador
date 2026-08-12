import threading

import easyocr
import numpy as np
import pymupdf
import torch
from typing_extensions import override

from classiflow.ingesta.extractors.base import ExtractorBase
from classiflow.ingesta.extractors.exceptions import OcrError
from classiflow.settings import Settings


class OCRExtractor(ExtractorBase):
    def __init__(self) -> None:
        self._reader: easyocr.Reader | None = None  # type: ignore[no-any-unimported]
        self._lock = threading.Lock()

    def warm(self) -> None:
        """Eagerly initializes the EasyOCR reader — call once at server startup so the
        model download/integrity-check happens before any request can race it."""
        self._get_reader()

    def _get_reader(self) -> easyocr.Reader:  # type: ignore[no-any-unimported]
        # Real double-checked locking, not @lru_cache: lru_cache's internal lock only
        # guards its cache dict, not the wrapped call itself, so two threads can both
        # miss the cache and both construct easyocr.Reader(...) concurrently. The
        # coordinator can run multiple jobs' background tasks at once, each potentially
        # needing OCR around the same time, so this is a real race, not a speculative one.
        if self._reader is None:
            with self._lock:
                if self._reader is None:
                    self._reader = easyocr.Reader(
                        [Settings.ocr_lang], gpu=torch.cuda.is_available()
                    )
        return self._reader

    @override
    def extract(self, file_bytes: bytes, filename: str) -> str:
        try:
            return self._read_pages(file_bytes)
        except pymupdf.FileDataError as exc:
            raise OcrError(filename, exc) from exc

    def _read_pages(self, file_bytes: bytes) -> str:
        reader = self._get_reader()
        lines: list[str] = []
        with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
            for page in doc:
                # dpi= renders directly at the requested resolution — more exact than
                # deriving a zoom Matrix from dpi/72 by hand.
                pixmap = page.get_pixmap(dpi=Settings.ocr_render_dpi)
                image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height, pixmap.width, pixmap.n
                )
                lines.extend(reader.readtext(image, detail=0, paragraph=True))
        return "\n".join(lines).strip()

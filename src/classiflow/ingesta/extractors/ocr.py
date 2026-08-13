from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
import pymupdf
from typing_extensions import override

from classiflow.ingesta.extractors.base import ExtractorBase
from classiflow.ingesta.extractors.exceptions import OcrError
from classiflow.settings import Settings

_OcrImage = npt.NDArray[np.uint8]


@runtime_checkable
class _OcrReader(Protocol):
    def readtext(self, image: _OcrImage, *, detail: int, paragraph: bool) -> list[str]: ...


class OCRExtractor(ExtractorBase):
    def __init__(self, reader: _OcrReader) -> None:
        self._reader = reader

    @override
    def extract(self, file_bytes: bytes, filename: str) -> str:
        try:
            return self._read_pages(file_bytes)
        except pymupdf.FileDataError as exc:
            raise OcrError(filename, exc) from exc

    def _read_pages(self, file_bytes: bytes) -> str:
        lines: list[str] = []
        with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
            for page in doc:
                # dpi= renders directly at the requested resolution — more exact than
                # deriving a zoom Matrix from dpi/72 by hand.
                pixmap = page.get_pixmap(dpi=Settings.ocr_render_dpi)
                image: _OcrImage = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height, pixmap.width, pixmap.n
                )
                lines.extend(self._reader.readtext(image, detail=0, paragraph=True))
        return "\n".join(lines).strip()

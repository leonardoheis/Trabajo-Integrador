import pymupdf
import pytest

from classiflow.ingesta.extractors.exceptions import OcrError
from classiflow.ingesta.extractors.ocr import OCRExtractor


class _FakeReader:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def readtext(self, _image: object, **_kwargs: object) -> list[str]:
        return self._lines


def _one_page_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page()
    return doc.tobytes()


def test_extract_reads_text_via_injected_reader() -> None:
    extractor = OCRExtractor(reader=_FakeReader(["hola", "mundo"]))

    result = extractor.extract(_one_page_pdf(), "scan.pdf")

    assert result == "hola\nmundo"


def test_extract_wraps_corrupt_pdf_as_ocr_error() -> None:
    extractor = OCRExtractor(reader=_FakeReader([]))

    with pytest.raises(OcrError):
        extractor.extract(b"not a pdf", "broken.pdf")

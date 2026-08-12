from collections.abc import Callable

import pytest

from classiflow.ingesta.extract import MIN_TEXT_FOR_OCR, MIN_USABLE_TEXT, extract_document
from classiflow.ingesta.extractors import ExtractorBase, MarkItDownError, OcrError

_LONG_TEXT = "x" * MIN_TEXT_FOR_OCR
_THIN_TEXT = "x" * (MIN_TEXT_FOR_OCR - 1)
_USABLE_OCR_TEXT = "y" * MIN_USABLE_TEXT
_UNUSABLE_OCR_TEXT = "y" * (MIN_USABLE_TEXT - 1)


class _StubExtractor(ExtractorBase):
    def __init__(self, fn: Callable[[bytes, str], str]) -> None:
        self._fn = fn

    def extract(self, file_bytes: bytes, filename: str) -> str:
        return self._fn(file_bytes, filename)


def test_markitdown_sufficient_text() -> None:
    def _fail_if_called(_file_bytes: bytes, _filename: str) -> str:
        pytest.fail("OCR must not be called")

    chain = [_StubExtractor(lambda _b, _f: _LONG_TEXT), _StubExtractor(_fail_if_called)]

    assert extract_document(b"%PDF-1.4 fake", "doc.pdf", chain=chain) == _LONG_TEXT


def test_ocr_fallback_when_text_thin() -> None:
    chain = [
        _StubExtractor(lambda _b, _f: _THIN_TEXT),
        _StubExtractor(lambda _b, _f: _USABLE_OCR_TEXT),
    ]

    assert extract_document(b"%PDF-1.4 fake", "scan.pdf", chain=chain) == _USABLE_OCR_TEXT


def test_both_fail_returns_empty() -> None:
    def _raise_markitdown(_b: bytes, filename: str) -> str:
        raise MarkItDownError(filename, ValueError("boom"))

    def _raise_ocr(_b: bytes, filename: str) -> str:
        raise OcrError(filename, ValueError("boom"))

    chain = [_StubExtractor(_raise_markitdown), _StubExtractor(_raise_ocr)]

    assert not extract_document(b"%PDF-1.4 fake", "broken.pdf", chain=chain)


def test_ocr_result_below_usable_threshold_returns_empty() -> None:
    chain = [
        _StubExtractor(lambda _b, _f: _THIN_TEXT),
        _StubExtractor(lambda _b, _f: _UNUSABLE_OCR_TEXT),
    ]

    assert not extract_document(b"%PDF-1.4 fake", "mostly-blank.pdf", chain=chain)


def test_thin_but_usable_markitdown_text_survives_ocr_failure() -> None:
    # MarkItDown found *some* usable text (above MIN_USABLE_TEXT, below the
    # MIN_TEXT_FOR_OCR trigger) and OCR then failed outright — the partial MarkItDown
    # result should still win rather than being discarded for an empty OCR attempt.
    thin_but_usable = "z" * (MIN_USABLE_TEXT + 1)

    def _raise_ocr(_b: bytes, filename: str) -> str:
        raise OcrError(filename, ValueError("boom"))

    chain = [_StubExtractor(lambda _b, _f: thin_but_usable), _StubExtractor(_raise_ocr)]

    assert extract_document(b"%PDF-1.4 fake", "partial.pdf", chain=chain) == thin_but_usable

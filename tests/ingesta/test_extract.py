from collections.abc import Callable

from classiflow.ingesta.config_extraction import ExtractionConfig
from classiflow.ingesta.extract import TextExtractor
from classiflow.ingesta.extractors import ExtractorBase, MarkItDownError, OcrError

_CONFIG = ExtractionConfig(min_text_for_ocr=50, min_usable_text=20, max_concurrent_extractions=2)

_LONG_TEXT = "x" * _CONFIG.min_text_for_ocr
_THIN_TEXT = "x" * (_CONFIG.min_text_for_ocr - 1)
_USABLE_OCR_TEXT = "y" * _CONFIG.min_usable_text
_UNUSABLE_OCR_TEXT = "y" * (_CONFIG.min_usable_text - 1)


class _StubExtractor(ExtractorBase):
    def __init__(self, name: str, fn: Callable[[bytes, str], str]) -> None:
        self._name = name
        self._fn = fn

    @property
    def name(self) -> str:
        return self._name

    def extract(self, file_bytes: bytes, filename: str) -> str:
        return self._fn(file_bytes, filename)


def test_markitdown_sufficient_text() -> None:
    def _fail_if_called(_file_bytes: bytes, _filename: str) -> str:
        msg = "OCR must not be called"
        raise AssertionError(msg)

    chain = [
        _StubExtractor("markitdown", lambda _b, _f: _LONG_TEXT),
        _StubExtractor("ocr", _fail_if_called),
    ]

    result = TextExtractor(chain, _CONFIG)(b"%PDF-1.4 fake", "doc.pdf")
    assert result.text == _LONG_TEXT
    assert result.extractor_used == "markitdown"
    assert result.char_count == len(_LONG_TEXT)


def test_ocr_fallback_when_text_thin() -> None:
    chain = [
        _StubExtractor("markitdown", lambda _b, _f: _THIN_TEXT),
        _StubExtractor("ocr", lambda _b, _f: _USABLE_OCR_TEXT),
    ]

    result = TextExtractor(chain, _CONFIG)(b"%PDF-1.4 fake", "scan.pdf")
    assert result.text == _USABLE_OCR_TEXT
    assert result.extractor_used == "ocr"


def test_both_fail_returns_empty() -> None:
    def _raise_markitdown(_b: bytes, filename: str) -> str:
        raise MarkItDownError(filename, ValueError("boom"))

    def _raise_ocr(_b: bytes, filename: str) -> str:
        raise OcrError(filename, ValueError("boom"))

    chain = [_StubExtractor("markitdown", _raise_markitdown), _StubExtractor("ocr", _raise_ocr)]

    result = TextExtractor(chain, _CONFIG)(b"%PDF-1.4 fake", "broken.pdf")
    assert not result.text
    assert not result.extractor_used
    assert result.char_count == 0


def test_ocr_result_below_usable_threshold_returns_empty() -> None:
    chain = [
        _StubExtractor("markitdown", lambda _b, _f: _THIN_TEXT),
        _StubExtractor("ocr", lambda _b, _f: _UNUSABLE_OCR_TEXT),
    ]

    result = TextExtractor(chain, _CONFIG)(b"%PDF-1.4 fake", "mostly-blank.pdf")
    # text is zeroed out (unusable), but extractor_used/char_count stay informative --
    # Stage 2's observability work (DocumentStep tracking) reads these even when the
    # extraction outcome itself was unusable.
    assert not result.text
    assert result.extractor_used == "ocr"
    assert result.char_count == len(_UNUSABLE_OCR_TEXT)


def test_thin_but_usable_markitdown_text_survives_ocr_failure() -> None:
    # MarkItDown found *some* usable text (above min_usable_text, below the
    # min_text_for_ocr trigger) and OCR then failed outright — the partial MarkItDown
    # result should still win rather than being discarded for an empty OCR attempt.
    thin_but_usable = "z" * (_CONFIG.min_usable_text + 1)

    def _raise_ocr(_b: bytes, filename: str) -> str:
        raise OcrError(filename, ValueError("boom"))

    chain = [
        _StubExtractor("markitdown", lambda _b, _f: thin_but_usable),
        _StubExtractor("ocr", _raise_ocr),
    ]

    result = TextExtractor(chain, _CONFIG)(b"%PDF-1.4 fake", "partial.pdf")
    assert result.text == thin_but_usable
    assert result.extractor_used == "markitdown"

"""Tests unitarios — document_ai/text_reader.py."""
from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock, patch

import pytest

from document_ai.text_reader import extract_text


@pytest.mark.unit
class TestExtractTextDispatch:
    def test_unknown_extension_returns_empty(self) -> None:
        result = extract_text(b"data", "file.xyz")
        assert result == ""

    def test_no_extension_returns_empty(self) -> None:
        result = extract_text(b"data", "noextension")
        assert result == ""


@pytest.mark.unit
class TestExtractFromPDF:
    def test_pdf_with_fitz(self, minimal_pdf_bytes: bytes) -> None:
        mock_fitz = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "page text"
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = extract_text(minimal_pdf_bytes, "doc.pdf")
        assert "page text" in result

    def test_pdf_extraction_failure_returns_empty(self, minimal_pdf_bytes: bytes) -> None:
        mock_fitz = MagicMock()
        mock_fitz.open.side_effect = RuntimeError("corrupt pdf")

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = extract_text(minimal_pdf_bytes, "bad.pdf")
        assert result == ""


@pytest.mark.unit
class TestExtractFromDOCX:
    def test_docx_success(self) -> None:
        from docx import Document
        buf = io.BytesIO()
        doc = Document()
        doc.add_paragraph("Hola municipalidad")
        doc.save(buf)

        result = extract_text(buf.getvalue(), "doc.docx")
        assert "Hola municipalidad" in result

    def test_docx_failure_returns_empty(self) -> None:
        result = extract_text(b"not a docx", "bad.docx")
        assert result == ""


@pytest.mark.unit
class TestExtractFromImage:
    def test_image_with_pytesseract(self, minimal_png_bytes: bytes) -> None:
        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "texto escaneado"
        mock_pil = MagicMock()
        mock_pil.Image.open.return_value = MagicMock()

        with patch.dict(sys.modules, {"pytesseract": mock_pytesseract, "PIL": mock_pil, "PIL.Image": mock_pil.Image}):
            result = extract_text(minimal_png_bytes, "scan.png")
        assert result == "texto escaneado"

    def test_image_pytesseract_not_installed_returns_empty(self, minimal_png_bytes: bytes) -> None:
        with patch.dict(sys.modules, {"pytesseract": None}):
            result = extract_text(minimal_png_bytes, "scan.png")
        assert result == ""

    def test_image_ocr_failure_returns_empty(self, minimal_png_bytes: bytes) -> None:
        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.side_effect = RuntimeError("tesseract error")

        with patch.dict(sys.modules, {"pytesseract": mock_pytesseract}):
            result = extract_text(minimal_png_bytes, "scan.jpg")
        assert result == ""

    def test_jpg_dispatched_to_image_reader(self, minimal_jpg_bytes: bytes) -> None:
        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "jpg text"
        mock_pil = MagicMock()

        with patch.dict(sys.modules, {"pytesseract": mock_pytesseract, "PIL": mock_pil, "PIL.Image": mock_pil.Image}):
            result = extract_text(minimal_jpg_bytes, "scan.jpg")
        assert result == "jpg text"

    def test_tiff_dispatched_to_image_reader(self) -> None:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (1, 1)).save(buf, format="TIFF")

        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "tiff text"
        mock_pil = MagicMock()

        with patch.dict(sys.modules, {"pytesseract": mock_pytesseract, "PIL": mock_pil, "PIL.Image": mock_pil.Image}):
            result = extract_text(buf.getvalue(), "scan.tiff")
        assert result == "tiff text"

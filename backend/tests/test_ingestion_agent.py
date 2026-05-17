"""Tests unitarios — ingestion_agent."""
from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import UploadFile

from agents.ingestion_agent import SUPPORTED_FORMATS, ingest


def _make_upload_file(content: bytes, filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=io.BytesIO(content),
        headers={"content-type": content_type},  # type: ignore[arg-type]
    )


@pytest.mark.unit
class TestIngestPDF:
    async def test_pdf_returns_ingestion_result(self, minimal_pdf_bytes: bytes) -> None:
        upload = _make_upload_file(minimal_pdf_bytes, "doc.pdf", "application/pdf")
        result, raw = await ingest(upload)
        assert result.filename == "doc.pdf"
        assert result.format == "pdf"
        assert result.size_bytes == len(minimal_pdf_bytes)
        assert raw == minimal_pdf_bytes

    async def test_pdf_size_is_correct(self, minimal_pdf_bytes: bytes) -> None:
        upload = _make_upload_file(minimal_pdf_bytes, "doc.pdf", "application/pdf")
        result, _ = await ingest(upload)
        assert result.size_bytes > 0

    async def test_pdf_preview_with_pymupdf(self, minimal_pdf_bytes: bytes) -> None:
        """Branch: fitz available."""
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_doc.page_count = 1
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_doc.__getitem__ = MagicMock(return_value=MagicMock(get_text=MagicMock(return_value="hello")))
        mock_fitz.open.return_value = mock_doc
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            upload = _make_upload_file(minimal_pdf_bytes, "doc.pdf", "application/pdf")
            result, _ = await ingest(upload)
        assert result.format == "pdf"

    async def test_pdf_preview_fallback_without_pymupdf(self, minimal_pdf_bytes: bytes) -> None:
        """Branch: fitz not available → fallback."""
        with patch.dict(sys.modules, {"fitz": None}):
            upload = _make_upload_file(minimal_pdf_bytes, "doc.pdf", "application/pdf")
            result, _ = await ingest(upload)
        assert "KB" in result.text_preview or result.format == "pdf"


@pytest.mark.unit
class TestIngestImage:
    async def test_png_accepted(self, minimal_png_bytes: bytes) -> None:
        upload = _make_upload_file(minimal_png_bytes, "scan.png", "image/png")
        result, _ = await ingest(upload)
        assert result.format == "png"
        assert "[Image file:" in result.text_preview

    async def test_jpg_accepted(self, minimal_jpg_bytes: bytes) -> None:
        upload = _make_upload_file(minimal_jpg_bytes, "scan.jpg", "image/jpeg")
        result, _ = await ingest(upload)
        assert result.format in {"jpg", "jpeg"}

    async def test_tiff_accepted(self, minimal_png_bytes: bytes) -> None:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (1, 1)).save(buf, format="TIFF")
        tiff_bytes = buf.getvalue()
        upload = _make_upload_file(tiff_bytes, "scan.tiff", "image/tiff")
        result, _ = await ingest(upload)
        assert result.format == "tiff"

    async def test_tif_extension_accepted(self, minimal_png_bytes: bytes) -> None:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (1, 1)).save(buf, format="TIFF")
        tiff_bytes = buf.getvalue()
        upload = _make_upload_file(tiff_bytes, "scan.tif", "image/tiff")
        result, _ = await ingest(upload)
        assert result.format == "tif"

    async def test_corrupt_image_raises(self) -> None:
        upload = _make_upload_file(b"notanimage", "bad.png", "image/png")
        with pytest.raises(ValueError, match="corrupt"):
            await ingest(upload)


@pytest.mark.unit
class TestIngestDOCX:
    async def test_docx_accepted(self) -> None:
        from docx import Document
        buf = io.BytesIO()
        doc = Document()
        doc.add_paragraph("Test paragraph")
        doc.save(buf)
        docx_bytes = buf.getvalue()
        upload = _make_upload_file(docx_bytes, "report.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        result, _ = await ingest(upload)
        assert result.format == "docx"
        assert "Test paragraph" in result.text_preview

    async def test_docx_extraction_failure_returns_placeholder(self) -> None:
        upload = _make_upload_file(b"not a docx", "bad.docx", "application/octet-stream")
        result, _ = await ingest(upload)
        assert result.format == "docx"
        assert "failed" in result.text_preview.lower()


@pytest.mark.unit
class TestIngestValidation:
    async def test_unsupported_format_raises(self) -> None:
        upload = _make_upload_file(b"data", "archivo.xlsx", "application/vnd.ms-excel")
        with pytest.raises(ValueError, match="Unsupported"):
            await ingest(upload)

    async def test_no_extension_raises(self) -> None:
        upload = _make_upload_file(b"data", "archivo", "application/octet-stream")
        with pytest.raises(ValueError):
            await ingest(upload)

    async def test_filename_preserved(self, minimal_pdf_bytes: bytes) -> None:
        upload = _make_upload_file(minimal_pdf_bytes, "contrato_2024.pdf", "application/pdf")
        result, _ = await ingest(upload)
        assert result.filename == "contrato_2024.pdf"

    async def test_no_filename_uses_unknown(self, minimal_pdf_bytes: bytes) -> None:
        upload = UploadFile(file=io.BytesIO(minimal_pdf_bytes))
        # No filename → ext will be "" → raises ValueError
        with pytest.raises(ValueError):
            await ingest(upload)

    def test_supported_formats_set(self) -> None:
        assert "pdf" in SUPPORTED_FORMATS
        assert "docx" in SUPPORTED_FORMATS
        assert "png" in SUPPORTED_FORMATS

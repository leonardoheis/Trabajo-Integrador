from __future__ import annotations

import io
import logging

from fastapi import UploadFile

from models import IngestionResult

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {"pdf", "docx", "jpg", "jpeg", "png", "tiff", "tif"}


async def ingest(file: UploadFile) -> tuple[IngestionResult, bytes]:
    """Read and validate an uploaded file.

    Returns the IngestionResult and the raw file bytes so callers
    don't have to seek back to the beginning.
    """
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported file format '.{ext}'. "
            f"Accepted formats: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )

    file_bytes = await file.read()
    size_bytes = len(file_bytes)
    text_preview = ""

    if ext == "docx":
        text_preview = _extract_docx_text(file_bytes)
    elif ext == "pdf":
        text_preview = _extract_pdf_preview(file_bytes, filename)
    else:
        _validate_image(file_bytes, filename)
        text_preview = f"[Image file: {filename}]"

    result = IngestionResult(
        filename=filename,
        format=ext,
        size_bytes=size_bytes,
        text_preview=text_preview[:500],
    )

    logger.info(
        "Ingested '%s' — format=%s size=%d bytes preview_chars=%d",
        filename,
        ext,
        size_bytes,
        len(text_preview),
    )
    return result, file_bytes


def _extract_docx_text(file_bytes: bytes) -> str:
    try:
        from docx import Document  # type: ignore

        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as exc:
        logger.warning("Could not extract text from DOCX: %s", exc)
        return "[DOCX text extraction failed]"


def _extract_pdf_preview(file_bytes: bytes, filename: str) -> str:
    # Basic metadata without a heavy PDF library dependency.
    # If PyMuPDF or pdfminer is available, use it; otherwise return size info.
    try:
        import fitz  # type: ignore  # PyMuPDF

        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            page_count = doc.page_count
            first_page_text = doc[0].get_text() if page_count > 0 else ""
            return f"[PDF: {page_count} page(s)]\n{first_page_text}"
    except ImportError:  # pragma: no cover
        pass

    # Fallback: report size only
    kb = len(file_bytes) / 1024
    return f"[PDF file: {filename}, {kb:.1f} KB — install PyMuPDF for text extraction]"


def _validate_image(file_bytes: bytes, filename: str) -> None:
    try:
        from PIL import Image  # type: ignore

        img = Image.open(io.BytesIO(file_bytes))
        img.verify()
        logger.debug(
            "Image '%s' validated: format=%s", filename, img.format
        )
    except Exception as exc:
        raise ValueError(f"Image file '{filename}' appears to be corrupt: {exc}") from exc

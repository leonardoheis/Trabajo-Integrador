"""Text extraction from PDF, DOCX, and image files using open-source libraries."""
from __future__ import annotations

import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Dispatch text extraction based on file extension."""
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext == "pdf":
        return _from_pdf(file_bytes)
    if ext == "docx":
        return _from_docx(file_bytes)
    if ext in {"jpg", "jpeg", "png", "tiff", "tif"}:
        return _from_image(file_bytes, filename)
    logger.warning("No text extractor available for extension '%s'.", ext)
    return ""


def _from_pdf(file_bytes: bytes) -> str:
    try:
        import fitz  # PyMuPDF

        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            pages = [page.get_text() for page in doc]
        return "\n".join(pages)
    except ImportError:  # pragma: no cover
        logger.warning("PyMuPDF not installed; PDF text extraction unavailable.")
        return ""
    except Exception as exc:
        logger.warning("PDF text extraction failed: %s", exc)
        return ""


def _from_docx(file_bytes: bytes) -> str:
    try:
        from docx import Document  # type: ignore

        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as exc:
        logger.warning("DOCX text extraction failed: %s", exc)
        return ""


def _from_image(file_bytes: bytes, filename: str) -> str:
    try:
        import pytesseract  # type: ignore
        from PIL import Image

        img = Image.open(io.BytesIO(file_bytes))
        return pytesseract.image_to_string(img, lang="spa+eng")
    except ImportError:
        logger.warning(
            "pytesseract not installed; OCR unavailable for '%s'. "
            "Install tesseract-ocr and the pytesseract package.",
            filename,
        )
        return ""
    except Exception as exc:
        logger.warning("Image OCR failed for '%s': %s", filename, exc)
        return ""

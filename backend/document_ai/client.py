"""Open-source document analysis client.

Replaces Azure AI Document Intelligence with local libraries:
  - PyMuPDF  → PDF text extraction
  - python-docx → DOCX text extraction
  - pytesseract (optional) → image OCR
  - Keyword classifier → document type + confidence
  - Regex extractor → structured field extraction
"""
from __future__ import annotations

import logging

from models import AzureAnalysisResult
from document_ai.classifier import classify
from document_ai.extractor import extract_fields
from document_ai.text_reader import extract_text

logger = logging.getLogger(__name__)


class DocumentAnalysisClient:
    """Analyze documents locally without external API calls."""

    async def analyze(self, file_bytes: bytes, filename: str) -> AzureAnalysisResult:
        text = extract_text(file_bytes, filename)
        doc_type, confidence = classify(text)
        fields = extract_fields(text, doc_type)

        logger.info(
            "Analyzed '%s': doc_type=%s confidence=%.4f extracted_fields=%d",
            filename,
            doc_type,
            confidence,
            len(fields),
        )

        return AzureAnalysisResult(
            doc_type=doc_type,
            confidence=confidence,
            fields=fields,
            raw_response={
                "text_preview": text[:500],
                "char_count": len(text),
                "engine": "document_ai",
            },
        )


_client: DocumentAnalysisClient | None = None


def get_client() -> DocumentAnalysisClient:
    global _client
    if _client is None:
        _client = DocumentAnalysisClient()
    return _client

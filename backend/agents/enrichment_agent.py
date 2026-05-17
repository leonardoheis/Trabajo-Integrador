from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from models import AzureAnalysisResult, DocumentType, IngestionResult

logger = logging.getLogger(__name__)

_DOC_TYPE_TAGS: dict[DocumentType, list[str]] = {
    DocumentType.INVOICE: ["financial", "invoice", "accounts-payable"],
    DocumentType.CONTRACT: ["legal", "contract", "agreement"],
    DocumentType.TAX_FORM: ["tax", "compliance", "government"],
    DocumentType.REPORT: ["report", "analysis", "internal"],
    DocumentType.UNKNOWN: ["unclassified"],
}


def enrich(
    ingestion_result: IngestionResult,
    azure_result: AzureAnalysisResult,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """Build enrichment metadata from ingestion + analysis results.

    Returns:
        dict with keys: tags, language, page_count, has_tables, processed_at
    """
    raw = azure_result.raw_response or {}

    tags = list(_DOC_TYPE_TAGS.get(azure_result.doc_type, ["unclassified"]))
    if ingestion_result.format in {"jpg", "jpeg", "png", "tiff", "tif"}:
        tags.append("image-based")
    if ingestion_result.format == "pdf":
        tags.append("pdf")

    language = _detect_language(raw, fields)
    page_count = _count_pages(raw, ingestion_result)
    has_tables = _has_tables(raw)

    processed_at = datetime.now(tz=timezone.utc).isoformat()

    metadata: dict[str, Any] = {
        "tags": tags,
        "language": language,
        "page_count": page_count,
        "has_tables": has_tables,
        "processed_at": processed_at,
    }

    logger.info(
        "Enrichment complete: doc_type=%s tags=%s lang=%s pages=%s has_tables=%s",
        azure_result.doc_type,
        tags,
        language,
        page_count,
        has_tables,
    )
    return metadata


def _detect_language(raw: dict[str, Any], fields: dict[str, Any]) -> str:
    # Azure may return a language hint in the raw response
    if "languages" in raw and raw["languages"]:
        first = raw["languages"][0]
        if isinstance(first, dict):
            return first.get("locale", "unknown")
        return str(first)
    return "unknown"


def _count_pages(raw: dict[str, Any], ingestion_result: IngestionResult) -> int:
    if "pages" in raw and isinstance(raw["pages"], list):
        return len(raw["pages"])
    # Images are always 1 page
    if ingestion_result.format in {"jpg", "jpeg", "png", "tiff", "tif"}:
        return 1
    return 0


def _has_tables(raw: dict[str, Any]) -> bool:
    tables = raw.get("tables", [])
    return bool(tables)

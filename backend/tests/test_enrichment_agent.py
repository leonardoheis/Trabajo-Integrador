"""Tests unitarios — enrichment_agent."""
from __future__ import annotations

import pytest

from agents.enrichment_agent import enrich
from models.document import AzureAnalysisResult, DocumentType, IngestionResult


def _pdf_ingestion(filename: str = "doc.pdf") -> IngestionResult:
    return IngestionResult(filename=filename, format="pdf", size_bytes=1024)


def _img_ingestion(filename: str = "scan.png", fmt: str = "png") -> IngestionResult:
    return IngestionResult(filename=filename, format=fmt, size_bytes=512)


def _azure_result(doc_type: DocumentType = DocumentType.INVOICE, confidence: float = 0.92, raw: dict | None = None) -> AzureAnalysisResult:
    return AzureAnalysisResult(
        doc_type=doc_type,
        confidence=confidence,
        fields={},
        raw_response=raw or {},
    )


@pytest.mark.unit
class TestEnrich:
    def test_returns_required_keys(self) -> None:
        meta = enrich(_pdf_ingestion(), _azure_result(), {})
        for key in ("tags", "language", "page_count", "has_tables", "processed_at"):
            assert key in meta

    def test_pdf_tag_added(self) -> None:
        meta = enrich(_pdf_ingestion(), _azure_result(), {})
        assert "pdf" in meta["tags"]

    def test_image_tag_added_for_png(self) -> None:
        meta = enrich(_img_ingestion(fmt="png"), _azure_result(), {})
        assert "image-based" in meta["tags"]

    def test_image_tag_added_for_jpeg(self) -> None:
        meta = enrich(_img_ingestion(fmt="jpeg"), _azure_result(), {})
        assert "image-based" in meta["tags"]

    def test_image_tag_added_for_tiff(self) -> None:
        meta = enrich(_img_ingestion(fmt="tiff"), _azure_result(), {})
        assert "image-based" in meta["tags"]

    def test_invoice_type_tags(self) -> None:
        meta = enrich(_pdf_ingestion(), _azure_result(DocumentType.INVOICE), {})
        assert "financial" in meta["tags"]
        assert "invoice" in meta["tags"]

    def test_contract_type_tags(self) -> None:
        meta = enrich(_pdf_ingestion(), _azure_result(DocumentType.CONTRACT), {})
        assert "legal" in meta["tags"]

    def test_tax_form_type_tags(self) -> None:
        meta = enrich(_pdf_ingestion(), _azure_result(DocumentType.TAX_FORM), {})
        assert "tax" in meta["tags"]

    def test_report_type_tags(self) -> None:
        meta = enrich(_pdf_ingestion(), _azure_result(DocumentType.REPORT), {})
        assert "report" in meta["tags"]

    def test_unknown_type_tags(self) -> None:
        meta = enrich(_pdf_ingestion(), _azure_result(DocumentType.UNKNOWN), {})
        assert "unclassified" in meta["tags"]

    def test_language_from_raw_dict(self) -> None:
        raw = {"languages": [{"locale": "es-AR"}]}
        meta = enrich(_pdf_ingestion(), _azure_result(raw=raw), {})
        assert meta["language"] == "es-AR"

    def test_language_from_raw_string(self) -> None:
        raw = {"languages": ["es"]}
        meta = enrich(_pdf_ingestion(), _azure_result(raw=raw), {})
        assert meta["language"] == "es"

    def test_language_unknown_when_missing(self) -> None:
        meta = enrich(_pdf_ingestion(), _azure_result(raw={}), {})
        assert meta["language"] == "unknown"

    def test_page_count_from_raw(self) -> None:
        raw = {"pages": [{}, {}, {}]}
        meta = enrich(_pdf_ingestion(), _azure_result(raw=raw), {})
        assert meta["page_count"] == 3

    def test_page_count_one_for_image(self) -> None:
        meta = enrich(_img_ingestion(fmt="jpg"), _azure_result(), {})
        assert meta["page_count"] == 1

    def test_page_count_zero_fallback(self) -> None:
        meta = enrich(_pdf_ingestion(), _azure_result(raw={}), {})
        assert meta["page_count"] == 0

    def test_has_tables_true(self) -> None:
        raw = {"tables": [{"cells": []}]}
        meta = enrich(_pdf_ingestion(), _azure_result(raw=raw), {})
        assert meta["has_tables"] is True

    def test_has_tables_false(self) -> None:
        meta = enrich(_pdf_ingestion(), _azure_result(raw={}), {})
        assert meta["has_tables"] is False

    def test_processed_at_is_iso_string(self) -> None:
        meta = enrich(_pdf_ingestion(), _azure_result(), {})
        from datetime import datetime
        datetime.fromisoformat(meta["processed_at"])

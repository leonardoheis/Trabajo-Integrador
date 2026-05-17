"""Tests unitarios — document_ai/client.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from document_ai.client import DocumentAnalysisClient, get_client
from models.document import DocumentType


@pytest.mark.unit
class TestDocumentAnalysisClient:
    async def test_analyze_returns_azure_analysis_result(self) -> None:
        client = DocumentAnalysisClient()
        with patch("document_ai.client.extract_text", return_value="factura vendedor total iva"):
            result = await client.analyze(b"bytes", "doc.pdf")
        assert result.doc_type == DocumentType.INVOICE
        assert 0.0 <= result.confidence <= 1.0

    async def test_analyze_empty_text_returns_unknown(self) -> None:
        client = DocumentAnalysisClient()
        with patch("document_ai.client.extract_text", return_value=""):
            result = await client.analyze(b"bytes", "blank.pdf")
        assert result.doc_type == DocumentType.UNKNOWN
        assert result.confidence == 0.0

    async def test_analyze_sets_raw_response_engine(self) -> None:
        client = DocumentAnalysisClient()
        with patch("document_ai.client.extract_text", return_value=""):
            result = await client.analyze(b"bytes", "doc.pdf")
        assert result.raw_response["engine"] == "document_ai"

    async def test_analyze_includes_char_count(self) -> None:
        client = DocumentAnalysisClient()
        text = "factura vendedor total"
        with patch("document_ai.client.extract_text", return_value=text):
            result = await client.analyze(b"bytes", "doc.pdf")
        assert result.raw_response["char_count"] == len(text)

    async def test_analyze_text_preview_truncated_to_500(self) -> None:
        client = DocumentAnalysisClient()
        long_text = "x" * 1000
        with patch("document_ai.client.extract_text", return_value=long_text):
            result = await client.analyze(b"bytes", "doc.pdf")
        assert len(result.raw_response["text_preview"]) == 500

    async def test_analyze_calls_extract_text_with_correct_args(self) -> None:
        client = DocumentAnalysisClient()
        with patch("document_ai.client.extract_text", return_value="") as mock_et:
            await client.analyze(b"pdf content", "myfile.pdf")
        mock_et.assert_called_once_with(b"pdf content", "myfile.pdf")

    async def test_analyze_extracts_fields_for_invoice(self) -> None:
        client = DocumentAnalysisClient()
        text = (
            "factura vendedor total iva neto\n"
            "Vendedor: Test Corp\n"
            "CUIT: 30-12345678-9\n"
        )
        with patch("document_ai.client.extract_text", return_value=text):
            result = await client.analyze(b"bytes", "inv.pdf")
        assert result.doc_type == DocumentType.INVOICE
        assert isinstance(result.fields, dict)


@pytest.mark.unit
class TestGetClient:
    def test_returns_same_instance(self) -> None:
        import document_ai.client as dc_module
        dc_module._client = None
        c1 = get_client()
        c2 = get_client()
        assert c1 is c2

    def test_returns_document_analysis_client(self) -> None:
        import document_ai.client as dc_module
        dc_module._client = None
        c = get_client()
        assert isinstance(c, DocumentAnalysisClient)

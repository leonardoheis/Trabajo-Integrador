"""Tests unitarios — field_extractor."""
from __future__ import annotations

import pytest

from agents.field_extractor import extract_fields
from models.document import AzureAnalysisResult, DocumentType


@pytest.mark.unit
class TestExtractFields:
    def test_invoice_known_fields_are_normalized(self, invoice_azure_result: AzureAnalysisResult) -> None:
        fields = extract_fields(invoice_azure_result, DocumentType.INVOICE)
        assert fields["vendor_name"] == "Acme Corp"
        assert fields["invoice_number"] == "INV-001"
        assert fields["amount_due"] == 1500.00
        assert fields["currency"] == "ARS"

    def test_missing_expected_fields_are_none(self, invoice_azure_result: AzureAnalysisResult) -> None:
        fields = extract_fields(invoice_azure_result, DocumentType.INVOICE)
        # vendor_address no está en el fixture
        assert fields.get("vendor_address") is None

    def test_unknown_doc_type_returns_empty(self, low_confidence_result: AzureAnalysisResult) -> None:
        fields = extract_fields(low_confidence_result, DocumentType.UNKNOWN)
        assert fields == {}

    def test_extra_raw_fields_are_included(self) -> None:
        result = AzureAnalysisResult(
            doc_type=DocumentType.REPORT,
            confidence=0.90,
            fields={"title": "Annual Report", "extra_field": "extra_value"},
            raw_response={},
        )
        fields = extract_fields(result, DocumentType.REPORT)
        assert fields["title"] == "Annual Report"
        assert fields["extra_field"] == "extra_value"

    def test_alias_map_translates_azure_field_names(self) -> None:
        result = AzureAnalysisResult(
            doc_type=DocumentType.INVOICE,
            confidence=0.91,
            fields={"VendorName": "Beta SA", "TotalTax": 300.0},
            raw_response={},
        )
        fields = extract_fields(result, DocumentType.INVOICE)
        assert fields["vendor_name"] == "Beta SA"
        assert fields["tax_amount"] == 300.0

    def test_contract_fields_extracted(self, contract_azure_result: AzureAnalysisResult) -> None:
        fields = extract_fields(contract_azure_result, DocumentType.CONTRACT)
        assert fields["party_a"] == "Municipalidad de Rosario"
        assert fields["party_b"] == "Proveedor S.A."

    def test_logs_warning_for_missing_fields(
        self, low_confidence_result: AzureAnalysisResult, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging
        result = AzureAnalysisResult(
            doc_type=DocumentType.INVOICE,
            confidence=0.88,
            fields={},  # ningún campo
            raw_response={},
        )
        with caplog.at_level(logging.WARNING, logger="agents.field_extractor"):
            extract_fields(result, DocumentType.INVOICE)
        assert "not found" in caplog.text.lower()

"""Tests unitarios — document_ai/extractor.py."""
from __future__ import annotations

import pytest

from document_ai.extractor import extract_fields
from models.document import DocumentType


@pytest.mark.unit
class TestExtractFieldsUnknown:
    def test_unknown_returns_empty(self) -> None:
        assert extract_fields("any text", DocumentType.UNKNOWN) == {}


@pytest.mark.unit
class TestExtractInvoiceFields:
    _TEXT = (
        "FACTURA N° 00123\n"
        "Vendedor: Acme Corp S.A.\n"
        "Cliente: Municipalidad de Rosario\n"
        "Fecha: 15/03/2024\n"
        "Vencimiento: 30/03/2024\n"
        "Subtotal: $1200,00\n"
        "Total: $1452,00 pesos\n"
        "CUIT: 30-71234567-8\n"
    )

    def test_vendor_name_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.INVOICE)
        assert fields["VendorName"] == "Acme Corp S.A."

    def test_customer_name_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.INVOICE)
        assert fields["CustomerName"] == "Municipalidad de Rosario"

    def test_invoice_id_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.INVOICE)
        assert fields["InvoiceId"] is not None

    def test_invoice_date_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.INVOICE)
        assert fields["InvoiceDate"] is not None

    def test_due_date_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.INVOICE)
        assert fields["DueDate"] is not None

    def test_amount_due_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.INVOICE)
        assert fields["AmountDue"] is not None

    def test_currency_is_ars(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.INVOICE)
        assert fields["CurrencyCode"] == "ARS"

    def test_cuit_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.INVOICE)
        assert fields["TaxpayerId"] == "30-71234567-8"

    def test_missing_fields_return_none(self) -> None:
        fields = extract_fields("factura sin datos", DocumentType.INVOICE)
        assert fields["VendorName"] is None
        assert fields["InvoiceDate"] is None
        assert fields["AmountDue"] is None


@pytest.mark.unit
class TestExtractContractFields:
    _TEXT = (
        "CONTRATO DE SERVICIO\n"
        "Primera parte: Municipalidad de Rosario\n"
        "Segunda parte: Proveedor S.A.\n"
        "Vigencia: 01/04/2024\n"
        "Vencimiento: 01/04/2025\n"
        "Valor: $50000\n"
        "Ley aplicable: Código Civil y Comercial\n"
    )

    def test_party_a_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.CONTRACT)
        assert fields["party_a"] == "Municipalidad de Rosario"

    def test_party_b_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.CONTRACT)
        assert fields["party_b"] == "Proveedor S.A."

    def test_effective_date_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.CONTRACT)
        assert fields["effective_date"] is not None

    def test_expiration_date_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.CONTRACT)
        assert fields["expiration_date"] is not None

    def test_contract_value_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.CONTRACT)
        assert fields["contract_value"] is not None

    def test_governing_law_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.CONTRACT)
        assert fields["governing_law"] == "Código Civil y Comercial"

    def test_missing_fields_return_none(self) -> None:
        fields = extract_fields("contrato sin datos", DocumentType.CONTRACT)
        assert fields["party_a"] is None
        assert fields["party_b"] is None


@pytest.mark.unit
class TestExtractTaxFormFields:
    _TEXT = (
        "DECLARACIÓN JURADA — AFIP\n"
        "Contribuyente: Juan Pérez\n"
        "CUIT: 20-98765432-1\n"
        "Período fiscal: 2023\n"
        "Fecha presentación: 30/04/2024\n"
        "Impuesto a pagar: $8500 pesos\n"
    )

    def test_taxpayer_name_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.TAX_FORM)
        assert fields["taxpayer_name"] == "Juan Pérez"

    def test_taxpayer_id_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.TAX_FORM)
        assert fields["taxpayer_id"] == "20-98765432-1"

    def test_tax_year_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.TAX_FORM)
        assert fields["tax_year"] == "2023"

    def test_tax_owed_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.TAX_FORM)
        assert fields["tax_owed"] is not None

    def test_refund_amount_is_none(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.TAX_FORM)
        assert fields["refund_amount"] is None

    def test_missing_fields_return_none(self) -> None:
        fields = extract_fields("ddjj sin datos", DocumentType.TAX_FORM)
        assert fields["taxpayer_name"] is None
        assert fields["tax_year"] is None


@pytest.mark.unit
class TestExtractReportFields:
    _TEXT = (
        "INFORME DE GESTIÓN MUNICIPAL\n"
        "Autor: Secretaría de Hacienda\n"
        "Fecha: 31/12/2023\n"
        "Área: Dirección de Finanzas\n"
        "Período analizado: ejercicio 2023\n"
    )

    def test_title_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.REPORT)
        assert fields["title"] is not None

    def test_author_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.REPORT)
        assert fields["author"] == "Secretaría de Hacienda"

    def test_date_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.REPORT)
        assert fields["date"] is not None

    def test_department_extracted(self) -> None:
        fields = extract_fields(self._TEXT, DocumentType.REPORT)
        assert fields["department"] == "Dirección de Finanzas"

    def test_missing_fields_return_none(self) -> None:
        fields = extract_fields("informe sin datos", DocumentType.REPORT)
        assert fields["author"] is None
        assert fields["date"] is None

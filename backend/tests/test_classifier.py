"""Tests unitarios — document_ai/classifier.py."""
from __future__ import annotations

import pytest

from document_ai.classifier import classify
from models.document import DocumentType


@pytest.mark.unit
class TestClassify:
    def test_empty_text_returns_unknown(self) -> None:
        doc_type, confidence = classify("")
        assert doc_type == DocumentType.UNKNOWN
        assert confidence == 0.0

    def test_whitespace_only_returns_unknown(self) -> None:
        doc_type, confidence = classify("   \n\t  ")
        assert doc_type == DocumentType.UNKNOWN
        assert confidence == 0.0

    def test_no_keyword_match_returns_unknown(self) -> None:
        doc_type, confidence = classify("el perro saltó la valla rápidamente")
        assert doc_type == DocumentType.UNKNOWN
        assert confidence == 0.0

    def test_invoice_keywords_detected(self) -> None:
        text = "FACTURA N° 001 — vendedor: Acme Corp — total: $1500 — iva incluido"
        doc_type, confidence = classify(text)
        assert doc_type == DocumentType.INVOICE
        assert confidence > 0.0

    def test_contract_keywords_detected(self) -> None:
        text = (
            "CONTRATO DE SERVICIO entre la municipalidad y el contratante. "
            "Cláusula 1: vigencia del acuerdo es de 12 meses."
        )
        doc_type, confidence = classify(text)
        assert doc_type == DocumentType.CONTRACT
        assert confidence > 0.0

    def test_tax_form_keywords_detected(self) -> None:
        text = (
            "DECLARACIÓN JURADA — AFIP — contribuyente CUIT 20-12345678-9 "
            "base imponible gravado retención impuesto"
        )
        doc_type, confidence = classify(text)
        assert doc_type == DocumentType.TAX_FORM
        assert confidence > 0.0

    def test_report_keywords_detected(self) -> None:
        text = (
            "INFORME DE GESTIÓN — análisis diagnóstico resultados período "
            "antecedentes conclusión recomendaciones ejercicio"
        )
        doc_type, confidence = classify(text)
        assert doc_type == DocumentType.REPORT
        assert confidence > 0.0

    def test_confidence_capped_at_one(self) -> None:
        # Text with every invoice keyword → hit_ratio = 1.0, confidence = min(1.0, 2.0) = 1.0
        text = (
            "factura remito comprobante importe subtotal total vendedor "
            "proveedor cliente iva neto condición de pago precio unitario cantidad"
        )
        _, confidence = classify(text)
        assert confidence <= 1.0

    def test_confidence_is_float_between_zero_and_one(self) -> None:
        _, confidence = classify("factura vendedor total")
        assert 0.0 <= confidence <= 1.0

    def test_case_insensitive(self) -> None:
        doc_type, _ = classify("FACTURA VENDEDOR TOTAL IVA")
        assert doc_type == DocumentType.INVOICE

    def test_returns_best_matching_type(self) -> None:
        # More contract keywords than any other type
        text = "contrato acuerdo convenio cláusula obligación vigencia plazo rescisión"
        doc_type, _ = classify(text)
        assert doc_type == DocumentType.CONTRACT

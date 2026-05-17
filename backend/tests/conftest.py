"""Fixtures compartidos para toda la suite de tests."""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import storage as storage_module
from models.document import (
    AuditEntry,
    AzureAnalysisResult,
    DocumentType,
    IngestionResult,
    JobRecord,
    JobStatus,
)


# ── Reset de estado global entre tests ────────────────────────

@pytest.fixture(autouse=True)
def reset_storage():
    storage_module._jobs.clear()
    storage_module._audit_log.clear()
    yield
    storage_module._jobs.clear()
    storage_module._audit_log.clear()


@pytest.fixture(autouse=True)
def reset_document_ai_client():
    import document_ai.client as dc_module
    dc_module._client = None
    yield
    dc_module._client = None


# ── Fixtures de modelos ────────────────────────────────────────

@pytest.fixture
def invoice_azure_result() -> AzureAnalysisResult:
    return AzureAnalysisResult(
        doc_type=DocumentType.INVOICE,
        confidence=0.92,
        fields={
            "VendorName": "Acme Corp",
            "InvoiceId": "INV-001",
            "InvoiceDate": "2024-01-15",
            "AmountDue": 1500.00,
            "CurrencyCode": "ARS",
        },
        raw_response={"model": "prebuilt-invoice"},
    )


@pytest.fixture
def low_confidence_result() -> AzureAnalysisResult:
    return AzureAnalysisResult(
        doc_type=DocumentType.UNKNOWN,
        confidence=0.45,
        fields={},
        raw_response={},
    )


@pytest.fixture
def contract_azure_result() -> AzureAnalysisResult:
    return AzureAnalysisResult(
        doc_type=DocumentType.CONTRACT,
        confidence=0.88,
        fields={
            "party_a": "Municipalidad de Rosario",
            "party_b": "Proveedor S.A.",
            "effective_date": "2024-03-01",
        },
        raw_response={},
    )


@pytest.fixture
def ingestion_result() -> IngestionResult:
    return IngestionResult(
        filename="factura_001.pdf",
        format="pdf",
        size_bytes=204_800,
        text_preview="FACTURA N° 001 - Acme Corp",
    )


@pytest.fixture
def pending_job() -> JobRecord:
    return JobRecord(
        filename="test_doc.pdf",
        status=JobStatus.PENDING,
    )


# ── Fixtures de archivos binarios ─────────────────────────────

@pytest.fixture
def minimal_pdf_bytes() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f\r\n"
        b"0000000009 00000 n\r\n"
        b"0000000058 00000 n\r\n"
        b"0000000115 00000 n\r\n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF"
    )


@pytest.fixture
def minimal_png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    img = Image.new("RGB", (1, 1), color=(255, 0, 0))
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def minimal_jpg_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def mock_azure_client(invoice_azure_result: AzureAnalysisResult) -> MagicMock:
    client = MagicMock()
    client.analyze = AsyncMock(return_value=invoice_azure_result)
    return client


# ── Fixtures de directorio de salida ──────────────────────────

@pytest.fixture
def tmp_output_dir(tmp_path, monkeypatch):
    from config import settings
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(settings, "OUTPUT_BASE_DIR", out)
    return out


# ── FastAPI TestClient ─────────────────────────────────────────

@pytest.fixture
def client() -> TestClient:
    from main import app
    return TestClient(app)

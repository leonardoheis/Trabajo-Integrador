"""Tests unitarios — routing_agent."""
from __future__ import annotations

import pytest

from agents.routing_agent import route
from models.document import DocumentType


FILE_BYTES = b"%PDF-1.4 minimal"


@pytest.mark.unit
class TestRoute:
    async def test_high_confidence_invoice_routed_to_invoices(self, tmp_output_dir) -> None:
        path = await route(
            job_id="job-001",
            doc_type=DocumentType.INVOICE,
            confidence=0.95,
            file_bytes=FILE_BYTES,
            filename="factura.pdf",
            metadata={},
        )
        assert "invoices" in path
        assert "job-001" in path

    async def test_high_confidence_contract_routed(self, tmp_output_dir) -> None:
        path = await route(
            job_id="job-002",
            doc_type=DocumentType.CONTRACT,
            confidence=0.90,
            file_bytes=FILE_BYTES,
            filename="contrato.pdf",
            metadata={},
        )
        assert "contracts" in path

    async def test_high_confidence_tax_form_routed(self, tmp_output_dir) -> None:
        path = await route(
            job_id="job-003",
            doc_type=DocumentType.TAX_FORM,
            confidence=0.90,
            file_bytes=FILE_BYTES,
            filename="ddjj.pdf",
            metadata={},
        )
        assert "tax_returns" in path

    async def test_high_confidence_report_routed(self, tmp_output_dir) -> None:
        path = await route(
            job_id="job-004",
            doc_type=DocumentType.REPORT,
            confidence=0.90,
            file_bytes=FILE_BYTES,
            filename="informe.pdf",
            metadata={},
        )
        assert "reports" in path

    async def test_unknown_doc_type_routed_to_review(self, tmp_output_dir) -> None:
        path = await route(
            job_id="job-005",
            doc_type=DocumentType.UNKNOWN,
            confidence=0.90,
            file_bytes=FILE_BYTES,
            filename="unknown.pdf",
            metadata={},
        )
        assert "review" in path

    async def test_low_confidence_routed_to_review(self, tmp_output_dir) -> None:
        path = await route(
            job_id="job-006",
            doc_type=DocumentType.INVOICE,
            confidence=0.40,
            file_bytes=FILE_BYTES,
            filename="factura.pdf",
            metadata={},
        )
        assert "review" in path

    async def test_file_is_written_to_disk(self, tmp_output_dir) -> None:
        content = b"file content here"
        path = await route(
            job_id="job-007",
            doc_type=DocumentType.INVOICE,
            confidence=0.95,
            file_bytes=content,
            filename="test.pdf",
            metadata={},
        )
        from pathlib import Path
        assert Path(path).read_bytes() == content

    async def test_audit_entry_created(self, tmp_output_dir) -> None:
        from storage import get_audit_log
        await route(
            job_id="job-008",
            doc_type=DocumentType.INVOICE,
            confidence=0.95,
            file_bytes=FILE_BYTES,
            filename="inv.pdf",
            metadata={"tags": ["financial"], "language": "es", "page_count": 1, "has_tables": False},
        )
        log = await get_audit_log()
        assert any(e.event == "file_routed" for e in log)

    async def test_audit_jsonl_written(self, tmp_output_dir) -> None:
        await route(
            job_id="job-009",
            doc_type=DocumentType.REPORT,
            confidence=0.92,
            file_bytes=FILE_BYTES,
            filename="rep.pdf",
            metadata={},
        )
        audit_file = tmp_output_dir / "audit.jsonl"
        assert audit_file.exists()
        assert "job-009" in audit_file.read_text(encoding="utf-8")

    async def test_filename_prefixed_with_job_id(self, tmp_output_dir) -> None:
        path = await route(
            job_id="abcde12345",
            doc_type=DocumentType.INVOICE,
            confidence=0.95,
            file_bytes=FILE_BYTES,
            filename="invoice.pdf",
            metadata={},
        )
        from pathlib import Path
        assert Path(path).name.startswith("abcde12")

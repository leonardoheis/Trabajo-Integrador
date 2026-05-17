"""Tests unitarios — modelos Pydantic."""
from __future__ import annotations

import pytest

from models.document import (
    AzureAnalysisResult,
    DocumentType,
    IngestionResult,
    JobRecord,
    JobStatus,
)


@pytest.mark.unit
class TestJobRecord:
    def test_default_status_is_pending(self) -> None:
        job = JobRecord(filename="test.pdf")
        assert job.status == JobStatus.PENDING

    def test_id_is_generated_automatically(self) -> None:
        job1 = JobRecord(filename="a.pdf")
        job2 = JobRecord(filename="b.pdf")
        assert job1.id != job2.id

    def test_id_is_valid_uuid_format(self) -> None:
        import uuid
        job = JobRecord(filename="test.pdf")
        uuid.UUID(job.id)  # no lanza si es UUID válido

    def test_result_is_none_by_default(self) -> None:
        job = JobRecord(filename="test.pdf")
        assert job.result is None
        assert job.output_path is None
        assert job.error is None

    def test_status_transitions_are_valid_enum_values(self) -> None:
        for status in JobStatus:
            job = JobRecord(filename="test.pdf", status=status)
            assert job.status == status


@pytest.mark.unit
class TestAzureAnalysisResult:
    def test_fields_default_to_empty_dict(self) -> None:
        result = AzureAnalysisResult(
            doc_type=DocumentType.UNKNOWN,
            confidence=0.5,
        )
        assert result.fields == {}
        assert result.raw_response == {}

    def test_confidence_accepts_zero_to_one(self) -> None:
        for value in [0.0, 0.5, 1.0]:
            r = AzureAnalysisResult(doc_type=DocumentType.REPORT, confidence=value)
            assert r.confidence == value

    def test_doc_type_enum_values(self) -> None:
        assert DocumentType.INVOICE == "invoice"
        assert DocumentType.CONTRACT == "contract"
        assert DocumentType.TAX_FORM == "tax_form"
        assert DocumentType.REPORT == "report"
        assert DocumentType.UNKNOWN == "unknown"


@pytest.mark.unit
class TestIngestionResult:
    def test_text_preview_defaults_to_empty(self) -> None:
        result = IngestionResult(filename="doc.pdf", format="pdf", size_bytes=1024)
        assert result.text_preview == ""

    def test_size_bytes_is_stored(self) -> None:
        result = IngestionResult(filename="doc.pdf", format="pdf", size_bytes=512_000)
        assert result.size_bytes == 512_000

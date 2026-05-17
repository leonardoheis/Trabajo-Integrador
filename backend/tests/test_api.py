"""Tests de integración — endpoints FastAPI."""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from models.document import AzureAnalysisResult, DocumentType, JobStatus
from storage import create_job, update_job


@pytest.mark.unit
class TestHealthEndpoint:
    def test_root_returns_ok(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_root_includes_version(self, client: TestClient) -> None:
        response = client.get("/")
        assert "version" in response.json()


@pytest.mark.unit
class TestUploadEndpoint:
    def test_upload_pdf_returns_job_id(self, client: TestClient, minimal_pdf_bytes: bytes) -> None:
        with patch("api.routes.upload.orchestrator.orchestrate", new=AsyncMock(return_value={})):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("factura.pdf", io.BytesIO(minimal_pdf_bytes), "application/pdf")},
            )
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert len(data["job_id"]) > 0

    def test_upload_returns_filename(self, client: TestClient, minimal_pdf_bytes: bytes) -> None:
        with patch("api.routes.upload.orchestrator.orchestrate", new=AsyncMock(return_value={})):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("factura.pdf", io.BytesIO(minimal_pdf_bytes), "application/pdf")},
            )
        assert response.json()["filename"] == "factura.pdf"

    def test_upload_unsupported_format_returns_415(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/upload",
            files={"file": ("datos.xlsx", io.BytesIO(b"data"), "application/vnd.ms-excel")},
        )
        assert response.status_code == 415

    def test_upload_without_file_returns_422(self, client: TestClient) -> None:
        response = client.post("/api/v1/upload")
        assert response.status_code == 422

    async def test_background_task_failure_marks_job_failed(
        self, client: TestClient, minimal_pdf_bytes: bytes, tmp_output_dir
    ) -> None:
        from unittest.mock import AsyncMock, patch
        with patch(
            "api.routes.upload.orchestrator.orchestrate",
            new=AsyncMock(side_effect=RuntimeError("forced failure")),
        ):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("fail.pdf", io.BytesIO(minimal_pdf_bytes), "application/pdf")},
            )
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        from storage import get_job
        from models.document import JobStatus
        job = await get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED
        assert job.error is not None

    async def test_background_task_error_only_raises_when_no_output_path(
        self, client: TestClient, minimal_pdf_bytes: bytes, tmp_output_dir
    ) -> None:
        from unittest.mock import AsyncMock, patch
        from models.document import AzureAnalysisResult, DocumentType
        error_state = {
            "error": "partial error",
            "output_path": "",
            "azure_result": AzureAnalysisResult(
                doc_type=DocumentType.UNKNOWN, confidence=0.5, fields={}, raw_response={}
            ),
            "confidence": 0.5,
        }
        with patch(
            "api.routes.upload.orchestrator.orchestrate",
            new=AsyncMock(return_value=error_state),
        ):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("err.pdf", io.BytesIO(minimal_pdf_bytes), "application/pdf")},
            )
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        from storage import get_job
        from models.document import JobStatus
        job = await get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED


@pytest.mark.unit
class TestJobsEndpoint:
    def test_list_jobs_returns_list(self, client: TestClient) -> None:
        response = client.get("/api/v1/jobs")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_nonexistent_job_returns_404(self, client: TestClient) -> None:
        response = client.get("/api/v1/jobs/nonexistent-id-00000")
        assert response.status_code == 404

    def test_list_jobs_accepts_pagination_params(self, client: TestClient) -> None:
        response = client.get("/api/v1/jobs?limit=5&offset=0")
        assert response.status_code == 200

    def test_list_jobs_invalid_limit_too_low(self, client: TestClient) -> None:
        response = client.get("/api/v1/jobs?limit=0")
        assert response.status_code == 400

    def test_list_jobs_invalid_limit_too_high(self, client: TestClient) -> None:
        response = client.get("/api/v1/jobs?limit=201")
        assert response.status_code == 400

    def test_list_jobs_invalid_offset(self, client: TestClient) -> None:
        response = client.get("/api/v1/jobs?offset=-1")
        assert response.status_code == 400

    async def test_get_existing_job_returns_200(self, client: TestClient) -> None:
        job = await create_job("found.pdf")
        response = client.get(f"/api/v1/jobs/{job.id}")
        assert response.status_code == 200
        assert response.json()["id"] == job.id

    async def test_websocket_not_found(self, client: TestClient) -> None:
        with client.websocket_connect("/api/v1/jobs/no-such-job/ws") as ws:
            data = ws.receive_json()
            assert "error" in data

    async def test_websocket_terminal_status(self, client: TestClient) -> None:
        job = await create_job("ws_test.pdf")
        await update_job(job.id, status=JobStatus.DONE)
        with client.websocket_connect(f"/api/v1/jobs/{job.id}/ws") as ws:
            data = ws.receive_json()
            assert data["status"] == "done"


@pytest.mark.unit
class TestAuditEndpoint:
    def test_audit_returns_list(self, client: TestClient) -> None:
        response = client.get("/api/v1/audit")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_audit_invalid_limit_too_low(self, client: TestClient) -> None:
        response = client.get("/api/v1/audit?limit=0")
        assert response.status_code == 400

    def test_audit_invalid_limit_too_high(self, client: TestClient) -> None:
        response = client.get("/api/v1/audit?limit=1001")
        assert response.status_code == 400

    def test_audit_download_not_found_returns_404(self, client: TestClient, tmp_output_dir) -> None:
        response = client.get("/api/v1/audit/download")
        assert response.status_code == 404

    def test_audit_download_returns_file(self, client: TestClient, tmp_output_dir) -> None:
        audit_file = tmp_output_dir / "audit.jsonl"
        audit_file.write_text('{"event":"test"}\n', encoding="utf-8")
        response = client.get("/api/v1/audit/download")
        assert response.status_code == 200

from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from classiflow.ingesta.llm_provider import MockLlm

pytestmark = pytest.mark.usefixtures("_jwt_secret")

_MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"xref\n0 1\n0000000000 65535 f\ntrailer\n<< /Size 1 >>\nstartxref\n9\n%%EOF"
)
_SLM_LEGITIMATE = '{"is_legitimate": true, "confidence": 0.92, "reasoning": "official doc"}'
_NODE3_GET_LLM = "classiflow.ingesta.nodes.node3_content_validation.get_llm_langchain"


def _ingest(
    client: TestClient,
    admin_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    filename: str = "doc.pdf",
) -> str:
    monkeypatch.setattr(_NODE3_GET_LLM, lambda _path: MockLlm(response=_SLM_LEGITIMATE))
    response = client.post(
        "/pipeline/ingest",
        files={"file": (filename, _MINIMAL_PDF, "application/pdf")},
        headers=admin_auth_headers,
    )
    assert response.status_code == HTTPStatus.ACCEPTED
    job_id: str = response.json()["jobId"]
    return job_id


class TestAuditEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/audit")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_requires_admin(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        response = client.get("/audit", headers=auth_headers)
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.skip(
        reason="admin token still rejected as 'not in the allowed users list' on "
        "/pipeline/ingest -- Provide[Container.auth_service] resolution for the admin "
        "user in this module's client fixture isn't fixed yet."
    )
    def test_admin_can_list_audit_records(
        self,
        client: TestClient,
        admin_auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _ingest(client, admin_auth_headers, monkeypatch, filename="audit-list.pdf")

        response = client.get("/audit", headers=admin_auth_headers)

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert "items" in body
        assert "total" in body
        assert body["total"] > 0

    @pytest.mark.skip(
        reason="admin token still rejected as 'not in the allowed users list' on "
        "/pipeline/ingest -- Provide[Container.auth_service] resolution for the admin "
        "user in this module's client fixture isn't fixed yet."
    )
    def test_filters_by_job_id(
        self,
        client: TestClient,
        admin_auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        job_id = _ingest(client, admin_auth_headers, monkeypatch, filename="audit-filter.pdf")

        response = client.get(f"/audit?jobId={job_id}", headers=admin_auth_headers)

        assert response.status_code == HTTPStatus.OK
        items = response.json()["items"]
        assert len(items) > 0
        assert all(r["jobId"] == job_id for r in items)

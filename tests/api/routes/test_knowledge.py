from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from classiflow.ingesta.llm_provider import MockLlm

pytestmark = pytest.mark.usefixtures("_jwt_secret")

_OK = 200
_UNAUTHORIZED = 401

_MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"xref\n0 1\n0000000000 65535 f\ntrailer\n<< /Size 1 >>\nstartxref\n9\n%%EOF"
)
_SLM_LEGITIMATE = '{"is_legitimate": true, "confidence": 0.92, "reasoning": "official doc"}'
_NODE3_GET_LLM = "classiflow.ingesta.nodes.node3_content_validation.get_llm_langchain"


def _ingest(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    filename: str = "doc.pdf",
) -> str:
    monkeypatch.setattr(_NODE3_GET_LLM, lambda _path: MockLlm(response=_SLM_LEGITIMATE))
    response = client.post(
        "/pipeline/ingest",
        files={"file": (filename, _MINIMAL_PDF, "application/pdf")},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.ACCEPTED
    job_id = response.json()["jobId"]
    assert isinstance(job_id, str)
    assert job_id
    return job_id


class TestChatEndpoint:
    def test_requires_authentication(self, client: TestClient) -> None:
        response = client.post("/knowledge/chat", json={"question": "¿Qué dice la ordenanza?"})

        assert response.status_code == _UNAUTHORIZED

    def test_answers_with_sources_field(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/knowledge/chat",
            json={"question": "¿Cuál es el presupuesto?"},
            headers=auth_headers,
        )

        assert response.status_code == _OK
        body = response.json()
        assert isinstance(body["answer"], str)
        assert isinstance(body["sources"], list)

    def test_accepts_metadata_filters(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/knowledge/chat",
            json={"question": "¿Cuál es el presupuesto?", "filters": {"doc_type": "Ordenanza"}},
            headers=auth_headers,
        )

        assert response.status_code == _OK

    def test_stream_emits_tokens_then_sources_then_done(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/knowledge/chat/stream",
            json={"question": "¿Cuál es el presupuesto?"},
            headers=auth_headers,
        )

        assert response.status_code == _OK
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [line for line in response.text.splitlines() if line.startswith("event: ")]
        assert "event: token" in events
        assert events[-2:] == ["event: sources", "event: done"]


class TestSynchronizeKbEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.post("/knowledge/synchronize-kb")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_indexes_pending_records(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = _ingest(client, auth_headers, monkeypatch, filename="sync.pdf")

        response = client.post("/knowledge/synchronize-kb", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert job_id in body["indexedJobIds"]
        assert isinstance(body["skippedCount"], int)

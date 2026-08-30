from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from classiflow.database.models import ClassificationRecord, EnrichedRecord
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.injections.test import TestContainer

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


class TestIndexDocumentEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.post("/knowledge/documents/some-job/index")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_returns_404_for_an_unknown_job(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post("/knowledge/documents/no-such-job/index", headers=auth_headers)
        assert response.status_code == HTTPStatus.NOT_FOUND

    async def test_rejects_a_document_not_yet_accepted(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_container: TestContainer,
    ) -> None:
        job_id = "pending-review-job"
        await test_container.enriched_record_repo().save(
            EnrichedRecord(
                job_id=job_id,
                cleaned_text="Artículo 1º...",
                entities={},
                metadata_={},
                filename="pending.pdf",
                sha256="a" * 64,
            )
        )
        await test_container.classification_record_repo().save(
            ClassificationRecord(
                job_id=job_id,
                enriched_id=1,
                label="ordenanzas",
                confidence=0.4,
                all_scores={"ordenanzas": 0.4},
                second_opinion_label=None,
                second_opinion_confidence=0.0,
                classifier_disagreement=False,
                ood_metrics=None,
                svm_scores={},
                svm_agrees_with_prediction=True,
                review_route="human_review",
                smells=["low_confidence"],
                risk_score=1,
                smell_review_suggested=False,
                foreign_municipality=None,
                judged_by_llm=False,
                judge_final_label=None,
                judge_reasoning=None,
                stored_path=None,
                human_overridden=False,
            )
        )

        response = client.post(f"/knowledge/documents/{job_id}/index", headers=auth_headers)
        assert response.status_code == HTTPStatus.CONFLICT

    def test_indexes_an_accepted_document(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = _ingest(client, auth_headers, monkeypatch, filename="manual-index.pdf")

        response = client.post(f"/knowledge/documents/{job_id}/index", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        body = response.json()["documentKb"]
        assert body is not None
        assert body["filename"] == "manual-index.pdf"


class TestDocumentKbEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/knowledge/documents/some-job")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_returns_null_when_not_indexed(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/knowledge/documents/no-such-job", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        assert response.json()["documentKb"] is None

    def test_returns_the_kb_record_once_indexed(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = _ingest(client, auth_headers, monkeypatch, filename="kb-detail.pdf")
        client.post("/knowledge/synchronize-kb", headers=auth_headers)

        response = client.get(f"/knowledge/documents/{job_id}", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        body = response.json()["documentKb"]
        assert body is not None
        assert body["filename"] == "kb-detail.pdf"
        assert isinstance(body["chunkCount"], int)

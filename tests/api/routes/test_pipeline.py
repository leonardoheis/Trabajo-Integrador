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
_SLM_NOT_LEGITIMATE = '{"is_legitimate": false, "confidence": 0.88, "reasoning": "spam"}'
_NODE3_GET_LLM = "classiflow.ingesta.nodes.node3_content_validation.get_llm_langchain"


def _upload(name: str = "doc.pdf") -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, _MINIMAL_PDF, "application/pdf")}


def _ingest(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    legitimate: bool,
    filename: str = "doc.pdf",
) -> str:
    monkeypatch.setattr(
        _NODE3_GET_LLM,
        lambda _path: MockLlm(response=_SLM_LEGITIMATE if legitimate else _SLM_NOT_LEGITIMATE),
    )
    response = client.post("/pipeline/ingest", files=_upload(filename), headers=auth_headers)
    assert response.status_code == HTTPStatus.ACCEPTED
    job_id = response.json()["jobId"]
    assert isinstance(job_id, str)
    assert job_id
    return job_id


class TestIngestEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.post("/pipeline/ingest", files=_upload())
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_accepted_returns_job_id(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ingest(client, auth_headers, monkeypatch, legitimate=True, filename="accept.pdf")


class TestEventsEndpoint:
    def test_unknown_job_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/pipeline/no-such-job/events", headers=auth_headers)
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/pipeline/whatever/events")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_stream_ends_with_done_event(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = _ingest(client, auth_headers, monkeypatch, legitimate=True, filename="events.pdf")

        response = client.get(f"/pipeline/{job_id}/events", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        min_blocks = 5  # 5 node events (started+passed pairs) + final pipeline_done
        blocks = [b for b in response.text.split("event: node_update") if b.strip()]
        assert len(blocks) >= min_blocks
        assert '"status":"done"' in blocks[-1]
        assert '"node":"pipeline"' in blocks[-1]


class TestReviewQueueEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/pipeline/review-queue")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_lists_review_job_with_document_steps(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = _ingest(client, auth_headers, monkeypatch, legitimate=False, filename="review.pdf")

        response = client.get("/pipeline/review-queue", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        items = response.json()
        item = next(i for i in items if i["jobId"] == job_id)
        assert item["status"] == "review"
        assert item["filename"] == "review.pdf"
        node_names = [s["node"] for s in item["documentSteps"]]
        assert node_names == [
            "node1_file_reception",
            "node2_format_validation",
            "extraction",
            "node3_content_validation",
        ]

    def test_accepted_job_not_in_queue(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = _ingest(client, auth_headers, monkeypatch, legitimate=True, filename="clean.pdf")

        response = client.get("/pipeline/review-queue", headers=auth_headers)
        assert job_id not in [i["jobId"] for i in response.json()]


class TestBulkIngestEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.post(
            "/pipeline/ingest-bulk", files=[("files", ("a.pdf", _MINIMAL_PDF, "application/pdf"))]
        )
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_returns_one_job_id_per_file(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_NODE3_GET_LLM, lambda _path: MockLlm(response=_SLM_LEGITIMATE))
        files = [
            ("files", ("bulk-a.pdf", _MINIMAL_PDF, "application/pdf")),
            ("files", ("bulk-b.pdf", _MINIMAL_PDF, "application/pdf")),
            ("files", ("bulk-c.pdf", _MINIMAL_PDF, "application/pdf")),
        ]
        response = client.post("/pipeline/ingest-bulk", files=files, headers=auth_headers)
        assert response.status_code == HTTPStatus.ACCEPTED
        job_ids = response.json()["jobIds"]
        assert len(job_ids) == len(files)
        assert len(set(job_ids)) == len(files)  # no duplicate job_ids


class TestDecisionEndpoint:
    def test_unknown_job_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/pipeline/no-such-job/decision", json={"decision": "accept"}, headers=auth_headers
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_job_not_in_review_returns_409(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = _ingest(client, auth_headers, monkeypatch, legitimate=True, filename="done.pdf")

        response = client.post(
            f"/pipeline/{job_id}/decision", json={"decision": "accept"}, headers=auth_headers
        )
        assert response.status_code == HTTPStatus.CONFLICT

    def test_accept_moves_job_out_of_review_queue(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = _ingest(
            client, auth_headers, monkeypatch, legitimate=False, filename="to_accept.pdf"
        )

        response = client.post(
            f"/pipeline/{job_id}/decision",
            json={"decision": "accept", "notes": "looks fine"},
            headers=auth_headers,
        )
        assert response.status_code == HTTPStatus.OK

        queue = client.get("/pipeline/review-queue", headers=auth_headers).json()
        assert job_id not in [i["jobId"] for i in queue]


class TestJobsEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/pipeline/jobs")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_default_status_running_excludes_terminal_jobs(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ingest(client, auth_headers, monkeypatch, legitimate=False, filename="rejected-jobs.pdf")

        response = client.get("/pipeline/jobs", headers=auth_headers)

        assert response.status_code == HTTPStatus.OK
        filenames = [j["filename"] for j in response.json()]
        assert "rejected-jobs.pdf" not in filenames

    def test_status_all_includes_terminal_jobs(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ingest(client, auth_headers, monkeypatch, legitimate=True, filename="all-jobs.pdf")

        response = client.get("/pipeline/jobs?status=all", headers=auth_headers)

        assert response.status_code == HTTPStatus.OK
        filenames = [j["filename"] for j in response.json()]
        assert "all-jobs.pdf" in filenames


class TestJobTimelineEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/pipeline/jobs/whatever/timeline")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unknown_job_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/pipeline/jobs/no-such-job/timeline", headers=auth_headers)
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_returns_merged_document_steps_and_audit_records(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = _ingest(
            client, auth_headers, monkeypatch, legitimate=True, filename="timeline.pdf"
        )

        response = client.get(f"/pipeline/jobs/{job_id}/timeline", headers=auth_headers)

        assert response.status_code == HTTPStatus.OK
        entries = response.json()
        assert len(entries) > 0
        assert all("node" in e and "timestamp" in e for e in entries)

from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from classiflow.database.models import ClassificationRecord, DocumentKb, EnrichedRecord, Job
from classiflow.injections.test import TestContainer

pytestmark = pytest.mark.usefixtures("_jwt_secret")


async def _seed_classified_job(
    test_container: TestContainer,
    job_id: str,
    filename: str,
    *,
    label: str = "ordenanzas",
    review_route: str = "accept",
    confidence: float = 0.95,
) -> None:
    await test_container.job_repo().create(Job(job_id=job_id, filename=filename, status="accepted"))
    enriched = EnrichedRecord(
        job_id=job_id,
        cleaned_text="Texto limpio de la ordenanza.",
        raw_text="Texto crudo extraido.",
        entities={"doc_type_hint": "ordenanza"},
        metadata_={"source": "manual_upload"},
    )
    await test_container.enriched_record_repo().save(enriched)
    await test_container.classification_record_repo().save(
        ClassificationRecord(
            job_id=job_id,
            enriched_id=enriched.id,
            label=label,
            confidence=confidence,
            all_scores={label: confidence},
            second_opinion_label=None,
            second_opinion_confidence=0.0,
            classifier_disagreement=False,
            ood_metrics=None,
            svm_scores={},
            svm_agrees_with_prediction=True,
            review_route=review_route,
            smells=[],
            risk_score=0,
            smell_review_suggested=False,
            foreign_municipality=None,
            judged_by_llm=False,
            judge_final_label=None,
            judge_reasoning=None,
            stored_path=None,
            human_overridden=False,
        )
    )
    storage = test_container.document_storage()
    await storage.save_staged(job_id, filename, b"%PDF-1.4 fake bytes")
    await storage.move_to_final(job_id, filename, f"classified/{label}")


class TestJobsListEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/jobs")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_returns_paginated_response(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/jobs", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert "items" in body
        assert "total" in body

    async def test_includes_classified_job(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_container: TestContainer,
    ) -> None:
        await _seed_classified_job(test_container, "job-list-1", "list-me.pdf")

        response = client.get("/jobs", headers=auth_headers)

        assert response.status_code == HTTPStatus.OK
        filenames = [j["filename"] for j in response.json()["items"]]
        assert "list-me.pdf" in filenames

    async def test_filters_by_label(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_container: TestContainer,
    ) -> None:
        await _seed_classified_job(
            test_container, "job-filter-1", "filter-me.pdf", label="decretos"
        )

        response = client.get("/jobs?label=decretos", headers=auth_headers)

        assert response.status_code == HTTPStatus.OK
        items = response.json()["items"]
        assert all(i["label"] == "decretos" for i in items)

    async def test_filters_by_review_route_camel_case_alias(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_container: TestContainer,
    ) -> None:
        await _seed_classified_job(
            test_container, "job-filter-2", "human-review-me.pdf", review_route="human_review"
        )

        response = client.get("/jobs?reviewRoute=human_review", headers=auth_headers)

        assert response.status_code == HTTPStatus.OK
        items = response.json()["items"]
        assert any(i["filename"] == "human-review-me.pdf" for i in items)
        assert all(i["reviewRoute"] == "human_review" for i in items)

    async def test_sorts_by_filename_ascending(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_container: TestContainer,
    ) -> None:
        await _seed_classified_job(test_container, "job-sort-1", "zebra.pdf", label="sort_test")
        await _seed_classified_job(test_container, "job-sort-2", "apple.pdf", label="sort_test")

        response = client.get(
            "/jobs?label=sort_test&sort=filename&sortDir=asc", headers=auth_headers
        )

        assert response.status_code == HTTPStatus.OK
        filenames = [i["filename"] for i in response.json()["items"]]
        assert filenames == ["apple.pdf", "zebra.pdf"]

    async def test_sorts_by_confidence_descending(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_container: TestContainer,
    ) -> None:
        await _seed_classified_job(
            test_container, "job-sort-3", "low.pdf", label="sort_test_2", confidence=0.4
        )
        await _seed_classified_job(
            test_container, "job-sort-4", "high.pdf", label="sort_test_2", confidence=0.9
        )

        response = client.get(
            "/jobs?label=sort_test_2&sort=confidence&sortDir=desc", headers=auth_headers
        )

        assert response.status_code == HTTPStatus.OK
        filenames = [i["filename"] for i in response.json()["items"]]
        assert filenames == ["high.pdf", "low.pdf"]

    async def test_marks_indexed_documents(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_container: TestContainer,
    ) -> None:
        await _seed_classified_job(test_container, "job-indexed-1", "indexed-me.pdf")
        await _seed_classified_job(test_container, "job-not-indexed-1", "not-indexed-me.pdf")
        await test_container.document_kb_repo().save(
            DocumentKb(
                job_id="job-indexed-1",
                sha256="a" * 64,
                filename="indexed-me.pdf",
                chunk_count=3,
            )
        )

        response = client.get("/jobs", headers=auth_headers)

        assert response.status_code == HTTPStatus.OK
        items = {i["filename"]: i for i in response.json()["items"]}
        assert items["indexed-me.pdf"]["indexed"] is True
        assert items["not-indexed-me.pdf"]["indexed"] is False


class TestJobDetailEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/jobs/whatever/detail")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unknown_job_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/jobs/no-such-job/detail", headers=auth_headers)
        assert response.status_code == HTTPStatus.NOT_FOUND

    async def test_returns_job_enriched_and_classification_data(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_container: TestContainer,
    ) -> None:
        await _seed_classified_job(test_container, "job-detail-1", "detail.pdf")

        response = client.get("/jobs/job-detail-1/detail", headers=auth_headers)

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["job"]["jobId"] == "job-detail-1"
        assert body["enriched"]["cleanedText"] == "Texto limpio de la ordenanza."
        assert body["classification"]["label"] == "ordenanzas"
        assert isinstance(body["audit"], list)


class TestDocumentFileEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/documents/whatever/file")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unknown_job_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/documents/no-such-job/file", headers=auth_headers)
        assert response.status_code == HTTPStatus.NOT_FOUND

    async def test_streams_the_stored_file_bytes(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_container: TestContainer,
    ) -> None:
        await _seed_classified_job(test_container, "job-file-1", "file.pdf")

        response = client.get("/documents/job-file-1/file", headers=auth_headers)

        assert response.status_code == HTTPStatus.OK
        assert response.content == b"%PDF-1.4 fake bytes"

from http import HTTPStatus
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from classiflow.database.models import ClassificationRecord, Job
from classiflow.injections.test import TestContainer

pytestmark = pytest.mark.usefixtures("_jwt_secret")


async def _seed_human_review_job(test_container: TestContainer, job_id: str, filename: str) -> None:
    await test_container.job_repo().create(Job(job_id=job_id, filename=filename, status="accepted"))
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
            stored_path=None,
            human_overridden=False,
        )
    )
    storage = test_container.document_storage()
    await storage.save_staged(job_id, filename, b"%PDF-1.4 fake bytes")
    await storage.move_to_final(job_id, filename, "review/human_review")


class TestReviewQueueEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/classification/review-queue")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    async def test_lists_records_needing_human_review(
        self, client: TestClient, auth_headers: dict[str, str], test_container: TestContainer
    ) -> None:
        await _seed_human_review_job(test_container, "review-job-001", "doc.pdf")

        response = client.get("/classification/review-queue", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        job_ids = [item["jobId"] for item in response.json()]
        assert "review-job-001" in job_ids


class TestClassificationDecisionEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.post("/classification/no-such-job/decision", json={"label": "ordenanzas"})
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_unknown_job_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/classification/no-such-job/decision",
            json={"label": "ordenanzas"},
            headers=auth_headers,
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    async def test_record_not_in_review_returns_409(
        self, client: TestClient, auth_headers: dict[str, str], test_container: TestContainer
    ) -> None:
        await _seed_human_review_job(test_container, "already-accepted-001", "doc.pdf")
        repo = test_container.classification_record_repo()
        record = await repo.find_by_job_id("already-accepted-001")
        assert record is not None
        record.review_route = "accept"
        await repo.save(record)

        response = client.post(
            "/classification/already-accepted-001/decision",
            json={"label": "ordenanzas"},
            headers=auth_headers,
        )
        assert response.status_code == HTTPStatus.CONFLICT

    async def test_accepted_decision_moves_file_and_flips_human_overridden(
        self, client: TestClient, auth_headers: dict[str, str], test_container: TestContainer
    ) -> None:
        await _seed_human_review_job(test_container, "decide-me-001", "doc.pdf")

        response = client.post(
            "/classification/decide-me-001/decision",
            json={"label": "decretos", "notes": "reviewed manually"},
            headers=auth_headers,
        )
        assert response.status_code == HTTPStatus.OK

        repo = test_container.classification_record_repo()
        record = await repo.find_by_job_id("decide-me-001")
        assert record is not None
        assert record.label == "decretos"
        assert record.review_route == "accept"
        assert record.human_overridden is True
        assert record.stored_path is not None
        assert Path("classified", "decretos").as_posix() in Path(record.stored_path).as_posix()

        queue = client.get("/classification/review-queue", headers=auth_headers).json()
        assert "decide-me-001" not in [item["jobId"] for item in queue]

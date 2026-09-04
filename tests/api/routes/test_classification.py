from http import HTTPStatus
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from classiflow.database.models import ClassificationRecord, Job
from classiflow.injections.test import TestContainer

pytestmark = pytest.mark.usefixtures("_jwt_secret")

_EXPECTED_LABELLED = 2
_EXPECTED_HALF = 0.5


async def _seed_human_review_job(
    test_container: TestContainer,
    job_id: str,
    filename: str,
    *,
    second_opinion_label: str | None = None,
    judged_by_llm: bool = False,
    judge_final_label: str | None = None,
    judge_reasoning: str | None = None,
) -> None:
    await test_container.job_repo().create(Job(job_id=job_id, filename=filename, status="accepted"))
    await test_container.classification_record_repo().save(
        ClassificationRecord(
            job_id=job_id,
            enriched_id=1,
            label="ordenanzas",
            confidence=0.4,
            all_scores={"ordenanzas": 0.4},
            second_opinion_label=second_opinion_label,
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
            judged_by_llm=judged_by_llm,
            judge_final_label=judge_final_label,
            judge_reasoning=judge_reasoning,
            stored_path=None,
            human_overridden=False,
            machine_review_route="human_review",
        )
    )
    storage = test_container.document_storage()
    await storage.save_staged(job_id, filename, b"%PDF-1.4 fake bytes")
    await storage.move_to_final(job_id, filename, "review/human_review")


async def _seed_classified_job(
    test_container: TestContainer,
    job_id: str,
    filename: str,
    *,
    label: str = "ordenanzas",
    expected_label: str | None = None,
) -> None:
    await test_container.job_repo().create(
        Job(job_id=job_id, filename=filename, status="classified")
    )
    await test_container.classification_record_repo().save(
        ClassificationRecord(
            job_id=job_id,
            enriched_id=1,
            label=label,
            confidence=0.95,
            all_scores={label: 0.95},
            second_opinion_confidence=0.0,
            classifier_disagreement=False,
            svm_scores={},
            svm_agrees_with_prediction=True,
            review_route="accept",
            smells=[],
            risk_score=0,
            smell_review_suggested=False,
            judged_by_llm=False,
            human_overridden=False,
            expected_label=expected_label,
        )
    )


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

    async def test_lists_judge_verdict_fields(
        self, client: TestClient, auth_headers: dict[str, str], test_container: TestContainer
    ) -> None:
        await _seed_human_review_job(
            test_container,
            "review-job-002",
            "doc.pdf",
            second_opinion_label="resoluciones_concejo_municipal",
            judged_by_llm=True,
            judge_final_label="resoluciones_concejo_municipal",
            judge_reasoning="second opinion's evidence is stronger here",
        )

        response = client.get("/classification/review-queue", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        item = next(i for i in response.json() if i["jobId"] == "review-job-002")
        assert item["secondOpinionLabel"] == "resoluciones_concejo_municipal"
        assert item["judgedByLlm"] is True
        assert item["judgeFinalLabel"] == "resoluciones_concejo_municipal"
        assert item["judgeReasoning"] == "second opinion's evidence is stronger here"


class TestAccuracyMetricsEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        assert client.get("/classification/metrics").status_code == HTTPStatus.UNAUTHORIZED

    async def test_reports_accuracy_over_labelled_records(
        self, client: TestClient, auth_headers: dict[str, str], test_container: TestContainer
    ) -> None:
        await _seed_classified_job(
            test_container, "metrics-hit", "ordenanza_1_2020.pdf", expected_label="ordenanzas"
        )
        await _seed_classified_job(
            test_container, "metrics-miss", "boletin_1_2020.pdf", expected_label="boletines"
        )

        response = client.get("/classification/metrics", headers=auth_headers)

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["labelled"] == _EXPECTED_LABELLED
        assert body["correct"] == 1
        assert body["strictAccuracy"] == pytest.approx(_EXPECTED_HALF)
        assert body["misses"][0]["expected"] == "boletines"
        assert body["misses"][0]["predicted"] == "ordenanzas"
        assert "compendios_de_boletines" in body["unevaluatedCategories"]


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

    async def test_override_preserves_the_machine_prediction(
        self, client: TestClient, auth_headers: dict[str, str], test_container: TestContainer
    ) -> None:
        # A correction is free ground truth: the reviewer's label is the truth and the
        # machine's original is the miss -- but only if the original survives being
        # overwritten by routing.
        await _seed_human_review_job(test_container, "capture-001", "doc.pdf")

        client.post(
            "/classification/capture-001/decision",
            json={"label": "decretos"},
            headers=auth_headers,
        )

        record = await test_container.classification_record_repo().find_by_job_id("capture-001")
        assert record is not None
        assert record.label == "decretos"  # the human's choice
        assert record.original_label == "ordenanzas"  # what the model actually said

    async def test_override_preserves_the_original_machine_route(
        self, client: TestClient, auth_headers: dict[str, str], test_container: TestContainer
    ) -> None:
        # The workflow route becomes accept, but the safety net's original decision must
        # survive it or a caught miss is later scored as uncaught.
        await _seed_human_review_job(test_container, "route-001", "doc.pdf")

        client.post(
            "/classification/route-001/decision",
            json={"label": "decretos"},
            headers=auth_headers,
        )

        record = await test_container.classification_record_repo().find_by_job_id("route-001")
        assert record is not None
        assert record.review_route == "accept"
        assert record.machine_review_route == "human_review"

    async def test_second_override_attempt_is_rejected(
        self, client: TestClient, auth_headers: dict[str, str], test_container: TestContainer
    ) -> None:
        # Overriding flips review_route to accept, and the endpoint only accepts records
        # still in human_review -- so a record can be corrected exactly once. This is what
        # makes original_label stable; the `or` guard in the endpoint is belt-and-braces
        # for any future caller that doesn't go through this route.
        await _seed_human_review_job(test_container, "capture-002", "doc.pdf")

        first = client.post(
            "/classification/capture-002/decision",
            json={"label": "decretos"},
            headers=auth_headers,
        )
        assert first.status_code == HTTPStatus.OK

        second = client.post(
            "/classification/capture-002/decision",
            json={"label": "boletines"},
            headers=auth_headers,
        )
        assert second.status_code == HTTPStatus.CONFLICT

        record = await test_container.classification_record_repo().find_by_job_id("capture-002")
        assert record is not None
        assert record.label == "decretos"
        assert record.original_label == "ordenanzas"

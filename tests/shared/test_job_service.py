from datetime import datetime, timezone

import pytest

from classiflow.database.models import DocumentStep, Job
from classiflow.database.repositories.document_steps import InMemoryDocumentStepsRepository
from classiflow.database.repositories.human_decision import InMemoryHumanDecisionRepository
from classiflow.database.repositories.job import InMemoryJobRepository
from classiflow.services.job.exceptions import JobNotFoundError, JobNotInReviewError
from classiflow.services.job.service import JobService

pytestmark = pytest.mark.anyio


def _service() -> tuple[
    JobService,
    InMemoryJobRepository,
    InMemoryDocumentStepsRepository,
    InMemoryHumanDecisionRepository,
]:
    job_repo = InMemoryJobRepository()
    steps_repo = InMemoryDocumentStepsRepository()
    decision_repo = InMemoryHumanDecisionRepository()
    return JobService(job_repo, steps_repo, decision_repo), job_repo, steps_repo, decision_repo


def _job(job_id: str, status: str) -> Job:
    now = datetime.now(timezone.utc)
    return Job(job_id=job_id, filename="doc.pdf", status=status, created_at=now, updated_at=now)


async def test_get_job_returns_the_job() -> None:
    service, job_repo, _, _ = _service()
    await job_repo.create(_job("job-1", "started"))

    result = await service.get_job("job-1")

    assert result is not None
    assert result.job_id == "job-1"


async def test_get_job_returns_none_for_missing_job() -> None:
    service, _, _, _ = _service()

    assert await service.get_job("missing") is None


async def test_list_review_queue_filters_to_review_status_and_includes_steps() -> None:
    service, job_repo, steps_repo, _ = _service()
    await job_repo.create(_job("job-review", "review"))
    await job_repo.create(_job("job-accepted", "accepted"))
    await steps_repo.save_step(
        DocumentStep(
            job_id="job-review",
            step_order=1,
            node="node1_file_reception",
            status="passed",
            passed=True,
            timestamp=datetime.now(timezone.utc),
        )
    )

    queue = await service.list_review_queue()

    assert len(queue) == 1
    job, steps = queue[0]
    assert job.job_id == "job-review"
    assert len(steps) == 1
    assert steps[0].node == "node1_file_reception"


async def test_submit_decision_raises_when_job_missing() -> None:
    service, _, _, _ = _service()

    with pytest.raises(JobNotFoundError):
        await service.submit_decision(
            "missing", decided_by="reviewer@x.com", decision="accept", notes=None
        )


async def test_submit_decision_raises_when_job_not_in_review() -> None:
    service, job_repo, _, _ = _service()
    await job_repo.create(_job("job-1", "accepted"))

    with pytest.raises(JobNotInReviewError):
        await service.submit_decision(
            "job-1", decided_by="reviewer@x.com", decision="accept", notes=None
        )


async def test_submit_decision_saves_decision_and_updates_status() -> None:
    service, job_repo, _, decision_repo = _service()
    await job_repo.create(_job("job-1", "review"))

    await service.submit_decision(
        "job-1", decided_by="reviewer@x.com", decision="accept", notes="looks good"
    )

    job = await job_repo.find_by_job_id("job-1")
    assert job is not None
    assert job.status == "accepted"
    decisions = await decision_repo.decisions_for_job("job-1")
    assert len(decisions) == 1
    assert decisions[0].decided_by == "reviewer@x.com"
    assert decisions[0].notes == "looks good"


async def test_submit_decision_reject_sets_rejected_status() -> None:
    service, job_repo, _, _ = _service()
    await job_repo.create(_job("job-1", "review"))

    await service.submit_decision(
        "job-1", decided_by="reviewer@x.com", decision="reject", notes=None
    )

    job = await job_repo.find_by_job_id("job-1")
    assert job is not None
    assert job.status == "rejected"

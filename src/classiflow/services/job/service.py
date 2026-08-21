from classiflow.database.models import DocumentStep, HumanDecision, Job
from classiflow.domain.repositories.document_steps import IDocumentStepsRepository
from classiflow.domain.repositories.human_decision import IHumanDecisionRepository
from classiflow.domain.repositories.job import IJobRepository
from classiflow.services.job.exceptions import JobNotFoundError, JobNotInReviewError

_DECISION_TO_STATUS = {"accept": "accepted", "reject": "rejected", "escalate": "escalated"}


class JobService:
    def __init__(
        self,
        job_repo: IJobRepository,
        document_steps_repo: IDocumentStepsRepository,
        human_decision_repo: IHumanDecisionRepository,
    ) -> None:
        self._job_repo = job_repo
        self._document_steps_repo = document_steps_repo
        self._human_decision_repo = human_decision_repo

    async def get_job(self, job_id: str) -> Job | None:
        return await self._job_repo.find_by_job_id(job_id)

    async def list_review_queue(self) -> list[tuple[Job, list[DocumentStep]]]:
        jobs = [j for j in await self._job_repo.list_all() if j.status == "review"]
        return [(job, await self._document_steps_repo.steps_for_job(job.job_id)) for job in jobs]

    async def submit_decision(
        self, job_id: str, *, decided_by: str, decision: str, notes: str | None
    ) -> None:
        job = await self._job_repo.find_by_job_id(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        if job.status != "review":
            raise JobNotInReviewError(job_id, job.status)
        await self._human_decision_repo.save(
            HumanDecision(job_id=job_id, decided_by=decided_by, decision=decision, notes=notes)
        )
        await self._job_repo.update_status(job_id, _DECISION_TO_STATUS[decision])

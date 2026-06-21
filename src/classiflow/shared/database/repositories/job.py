from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.shared.database.models import Job


class SqlJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, job: Job) -> None:
        self._session.add(job)
        await self._session.flush()

    async def find_by_job_id(self, job_id: str) -> Job | None:
        result = await self._session.execute(select(Job).where(Job.job_id == job_id))
        return result.scalar_one_or_none()

    async def update_status(self, job_id: str, status: str) -> None:
        job = await self.find_by_job_id(job_id)
        if job is not None:
            job.status = status
            await self._session.flush()

    async def list_all(self) -> list[Job]:
        result = await self._session.execute(select(Job).order_by(Job.created_at))
        return list(result.scalars().all())


class InMemoryJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    async def create(self, job: Job) -> None:
        self._jobs[job.job_id] = job

    async def find_by_job_id(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def update_status(self, job_id: str, status: str) -> None:
        job = self._jobs.get(job_id)
        if job is not None:
            job.status = status

    async def list_all(self) -> list[Job]:
        return list(self._jobs.values())

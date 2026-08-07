from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.shared.database.models import DocumentStep


class SqlDocumentStepsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_step(self, step: DocumentStep) -> None:
        self._session.add(step)
        await self._session.flush()

    async def steps_for_job(self, job_id: str) -> list[DocumentStep]:
        result = await self._session.execute(
            select(DocumentStep)
            .where(DocumentStep.job_id == job_id)
            .order_by(DocumentStep.step_order)
        )
        return list(result.scalars().all())


class InMemoryDocumentStepsRepository:
    def __init__(self) -> None:
        self._steps: list[DocumentStep] = []

    async def save_step(self, step: DocumentStep) -> None:
        self._steps.append(step)

    async def steps_for_job(self, job_id: str) -> list[DocumentStep]:
        return sorted(
            [s for s in self._steps if s.job_id == job_id],
            key=lambda s: s.step_order,
        )

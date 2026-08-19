from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.database.models import ClassificationRecord

_HUMAN_REVIEW_ROUTE = "human_review"


class SqlClassificationRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: ClassificationRecord) -> None:
        self._session.add(record)
        await self._session.flush()

    async def find_by_job_id(self, job_id: str) -> ClassificationRecord | None:
        result = await self._session.execute(
            select(ClassificationRecord).where(ClassificationRecord.job_id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_needing_human_review(self) -> list[ClassificationRecord]:
        result = await self._session.execute(
            select(ClassificationRecord).where(
                ClassificationRecord.review_route == _HUMAN_REVIEW_ROUTE
            )
        )
        return list(result.scalars().all())


class InMemoryClassificationRecordRepository:
    def __init__(self) -> None:
        self._records: dict[str, ClassificationRecord] = {}

    async def save(self, record: ClassificationRecord) -> None:
        self._records[record.job_id] = record

    async def find_by_job_id(self, job_id: str) -> ClassificationRecord | None:
        return self._records.get(job_id)

    async def list_needing_human_review(self) -> list[ClassificationRecord]:
        return [r for r in self._records.values() if r.review_route == _HUMAN_REVIEW_ROUTE]

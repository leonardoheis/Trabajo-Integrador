from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.classification.domain.review_route import ReviewRoute
from classiflow.database.models import ClassificationRecord


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
                ClassificationRecord.review_route == ReviewRoute.HUMAN_REVIEW
            )
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[ClassificationRecord]:
        result = await self._session.execute(select(ClassificationRecord))
        return list(result.scalars().all())


class InMemoryClassificationRecordRepository:
    def __init__(self) -> None:
        self._records: dict[str, ClassificationRecord] = {}

    async def save(self, record: ClassificationRecord) -> None:
        # Mirrors what a real SqlClassificationRecordRepository.save() gets for free
        # from the column's server_default=func.now() -- only fires on a real SQL
        # INSERT, so the in-memory repo must set it explicitly on first save.
        if record.created_at is None:
            record.created_at = datetime.now(timezone.utc)
        self._records[record.job_id] = record

    async def find_by_job_id(self, job_id: str) -> ClassificationRecord | None:
        return self._records.get(job_id)

    async def list_needing_human_review(self) -> list[ClassificationRecord]:
        return [r for r in self._records.values() if r.review_route == ReviewRoute.HUMAN_REVIEW]

    async def list_all(self) -> list[ClassificationRecord]:
        return list(self._records.values())

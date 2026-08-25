from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.database.models import DocumentKb, EnrichedRecord


class SqlEnrichedRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: EnrichedRecord) -> None:
        self._session.add(record)
        await self._session.flush()

    async def find_by_job_id(self, job_id: str) -> EnrichedRecord | None:
        result = await self._session.execute(
            select(EnrichedRecord).where(EnrichedRecord.job_id == job_id)
        )
        return result.scalar_one_or_none()

    async def find_unindexed(self) -> list[EnrichedRecord]:
        stmt = select(EnrichedRecord).where(
            ~exists(select(DocumentKb.id).where(DocumentKb.enriched_record_id == EnrichedRecord.id))
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class InMemoryEnrichedRecordRepository:
    def __init__(self) -> None:
        self._records: dict[str, EnrichedRecord] = {}
        self._next_id = 1

    async def save(self, record: EnrichedRecord) -> None:
        # Mirrors what a real SqlEnrichedRecordRepository.save() gets for free from
        # AsyncSession.flush() -- an autoincrement id. Nothing read record.id before
        # Task 16 (ClassificationRecord.enriched_id is the first FK that does), so this
        # was a latent gap, not previously a bug in practice.
        if record.id is None:
            record.id = self._next_id
            self._next_id += 1
        self._records[record.job_id] = record

    async def find_by_job_id(self, job_id: str) -> EnrichedRecord | None:
        return self._records.get(job_id)

    async def find_unindexed(self) -> list[EnrichedRecord]:
        # This double has no visibility into document_kb rows, so it cannot model the
        # NOT EXISTS join the SQL implementation does -- it simply returns every saved
        # record. Real "already indexed" exclusion is covered by a SQLite-backed test
        # against SqlEnrichedRecordRepository instead.
        return list(self._records.values())

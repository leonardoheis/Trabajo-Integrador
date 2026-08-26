from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.database.models import AuditRecord


class AuditDetail(BaseModel):
    model_config = ConfigDict(extra="allow")


class SqlAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: AuditRecord) -> None:
        self._session.add(record)
        await self._session.flush()

    async def list_for_job(self, job_id: str) -> list[AuditRecord]:
        result = await self._session.execute(
            select(AuditRecord).where(AuditRecord.job_id == job_id).order_by(AuditRecord.timestamp)
        )
        return list(result.scalars().all())

    async def list_filtered(
        self,
        job_id: str | None,
        node: str | None,
        event: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AuditRecord], int]:
        stmt = select(AuditRecord)
        if job_id is not None:
            stmt = stmt.where(AuditRecord.job_id == job_id)
        if node is not None:
            stmt = stmt.where(AuditRecord.node == node)
        if event is not None:
            stmt = stmt.where(AuditRecord.event == event)
        if date_from is not None:
            stmt = stmt.where(AuditRecord.timestamp >= date_from)
        if date_to is not None:
            stmt = stmt.where(AuditRecord.timestamp <= date_to)

        count_result = await self._session.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = count_result.scalar_one()

        paged_stmt = (
            stmt
            .order_by(AuditRecord.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self._session.execute(paged_stmt)
        return list(result.scalars().all()), total


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    async def save(self, record: AuditRecord) -> None:
        self._records.append(record)

    async def list_for_job(self, job_id: str) -> list[AuditRecord]:
        return [r for r in self._records if r.job_id == job_id]

    async def list_filtered(
        self,
        job_id: str | None,
        node: str | None,
        event: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AuditRecord], int]:
        matches = [
            r
            for r in self._records
            if (job_id is None or r.job_id == job_id)
            and (node is None or r.node == node)
            and (event is None or r.event == event)
            and (date_from is None or r.timestamp >= date_from)
            and (date_to is None or r.timestamp <= date_to)
        ]
        matches.sort(key=lambda r: r.timestamp, reverse=True)
        start = (page - 1) * page_size
        return matches[start : start + page_size], len(matches)


def make_audit_record(
    job_id: str,
    node: str,
    event: str,
    duration_ms: int | None = None,
    detail: AuditDetail | None = None,
) -> AuditRecord:
    # AuditRecord.timestamp's server_default only applies on a real SQL INSERT -- a
    # bare, unflushed instance (as InMemoryAuditRepository always stays) needs its own
    # Python-side value so it round-trips correctly through in-memory-only test flows,
    # matching what every real DB row always has the moment it exists.
    return AuditRecord(
        job_id=job_id,
        node=node,
        event=event,
        duration_ms=duration_ms,
        detail=detail.model_dump() if detail else None,
        timestamp=datetime.now(timezone.utc),
    )

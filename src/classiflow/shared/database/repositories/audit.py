from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import select

from classiflow.shared.database.models import AuditRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class IAuditRepository(Protocol):
    async def save(self, record: AuditRecord) -> None: ...
    async def list_for_job(self, job_id: str) -> list[AuditRecord]: ...


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


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    async def save(self, record: AuditRecord) -> None:
        self._records.append(record)

    async def list_for_job(self, job_id: str) -> list[AuditRecord]:
        return [r for r in self._records if r.job_id == job_id]


def make_audit_record(
    job_id: str,
    agent: str,
    event: str,
    duration_ms: int | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditRecord:
    return AuditRecord(
        job_id=job_id,
        agent=agent,
        event=event,
        duration_ms=duration_ms,
        detail=detail,
    )

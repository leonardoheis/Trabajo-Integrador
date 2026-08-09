from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
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


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    async def save(self, record: AuditRecord) -> None:
        self._records.append(record)

    async def list_for_job(self, job_id: str) -> list[AuditRecord]:
        return [r for r in self._records if r.job_id == job_id]


def make_audit_record(
    job_id: str,
    node: str,
    event: str,
    duration_ms: int | None = None,
    detail: AuditDetail | None = None,
) -> AuditRecord:
    return AuditRecord(
        job_id=job_id,
        node=node,
        event=event,
        duration_ms=duration_ms,
        detail=detail.model_dump() if detail else None,
    )

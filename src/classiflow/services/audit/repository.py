from typing import Protocol

from classiflow.database.models import AuditRecord


class IAuditRepository(Protocol):
    async def save(self, record: AuditRecord) -> None: ...
    async def list_for_job(self, job_id: str) -> list[AuditRecord]: ...

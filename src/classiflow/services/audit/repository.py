from datetime import datetime
from typing import Protocol

from classiflow.database.models import AuditRecord


class IAuditRepository(Protocol):
    async def save(self, record: AuditRecord) -> None: ...
    async def list_for_job(self, job_id: str) -> list[AuditRecord]: ...

    async def list_filtered(
        self,
        job_id: str | None,
        node: str | None,
        event: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AuditRecord], int]: ...

from datetime import datetime

from classiflow.api.schemas import BaseSchema
from classiflow.database.models import AuditRecord


class AuditRecordSchema(BaseSchema):
    job_id: str
    node: str
    event: str
    timestamp: datetime
    duration_ms: int | None
    detail: dict[str, object] | None

    @classmethod
    def from_model(cls, record: AuditRecord) -> "AuditRecordSchema":
        return cls(
            job_id=record.job_id,
            node=record.node,
            event=record.event,
            timestamp=record.timestamp,
            duration_ms=record.duration_ms,
            detail=record.detail,
        )


class AuditPage(BaseSchema):
    items: list[AuditRecordSchema]
    total: int
    page: int
    page_size: int

from datetime import datetime
from typing import Literal

from classiflow.api.schemas import BaseSchema
from classiflow.database.models import DocumentStep


class IngestResponse(BaseSchema):
    job_id: str


class BulkIngestResponse(BaseSchema):
    job_ids: list[str]


class SynchronizeKbResponse(BaseSchema):
    indexed_job_ids: list[str]
    skipped_count: int


class DocumentStepSchema(BaseSchema):
    step_order: int
    node: str
    status: str
    passed: bool
    rejection_reason: str | None
    duration_ms: int | None
    detail: dict[str, object] | None
    timestamp: datetime

    @classmethod
    def from_model(cls, step: DocumentStep) -> "DocumentStepSchema":
        return cls(
            step_order=step.step_order,
            node=step.node,
            status=step.status,
            passed=step.passed,
            rejection_reason=step.rejection_reason,
            duration_ms=step.duration_ms,
            detail=step.detail,
            timestamp=step.timestamp,
        )


class ReviewQueueItem(BaseSchema):
    job_id: str
    filename: str
    status: str
    rejection_reason: str | None
    created_at: datetime
    document_steps: list[DocumentStepSchema]


class DecisionRequest(BaseSchema):
    decision: Literal["accept", "reject", "escalate"]
    notes: str | None = None


class JobSummary(BaseSchema):
    job_id: str
    filename: str
    status: str
    created_at: datetime
    updated_at: datetime


class TimelineEntry(BaseSchema):
    node: str
    status: str
    passed: bool | None
    detail: dict[str, object] | None
    timestamp: datetime
    duration_ms: int | None

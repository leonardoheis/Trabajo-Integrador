from datetime import datetime

from classiflow.api.schemas import BaseSchema
from classiflow.database.models import ClassificationRecord


class ReviewQueueItem(BaseSchema):
    job_id: str
    label: str | None
    confidence: float
    review_route: str
    smells: list[str]
    risk_score: int
    smell_review_suggested: bool
    foreign_municipality: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, record: ClassificationRecord) -> "ReviewQueueItem":
        return cls(
            job_id=record.job_id,
            label=record.label,
            confidence=record.confidence,
            review_route=record.review_route,
            smells=record.smells,
            risk_score=record.risk_score,
            smell_review_suggested=record.smell_review_suggested,
            foreign_municipality=record.foreign_municipality,
            created_at=record.created_at,
        )


class ClassificationDecisionRequest(BaseSchema):
    label: str
    notes: str | None = None

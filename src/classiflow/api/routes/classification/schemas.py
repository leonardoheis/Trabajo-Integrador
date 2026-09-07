from datetime import datetime
from typing import Annotated

from pydantic import StringConstraints

from classiflow.api.schemas import BaseSchema
from classiflow.database.models import ClassificationRecord


class ReviewQueueItem(BaseSchema):
    job_id: str
    label: str | None
    confidence: float
    second_opinion_label: str | None
    review_route: str
    smells: list[str]
    risk_score: int
    smell_review_suggested: bool
    foreign_municipality: str | None
    judged_by_llm: bool
    judge_final_label: str | None
    judge_reasoning: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, record: ClassificationRecord) -> "ReviewQueueItem":
        return cls(
            job_id=record.job_id,
            label=record.label,
            confidence=record.confidence,
            second_opinion_label=record.second_opinion_label,
            review_route=record.review_route,
            smells=record.smells,
            risk_score=record.risk_score,
            smell_review_suggested=record.smell_review_suggested,
            foreign_municipality=record.foreign_municipality,
            judged_by_llm=record.judged_by_llm,
            judge_final_label=record.judge_final_label,
            judge_reasoning=record.judge_reasoning,
            created_at=record.created_at,
        )


class ClassificationDecisionRequest(BaseSchema):
    label: str
    notes: str | None = None


class ClassificationReopenRequest(BaseSchema):
    """Why a decided classification is being returned to the review queue.

    The reason is mandatory: a reopen overrides someone else's judgement, and the audit
    log is the only record of why.
    """

    # Trimmed before validation, so "   " fails min_length rather than passing as a
    # non-empty string that means nothing.
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

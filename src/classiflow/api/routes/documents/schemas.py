from datetime import datetime

from classiflow.api.routes.audit.schemas import AuditRecordSchema
from classiflow.api.schemas import BaseSchema
from classiflow.database.models import ClassificationRecord, EnrichedRecord, Job


class ClassificationSummary(BaseSchema):
    job_id: str
    filename: str
    label: str | None
    review_route: str
    confidence: float
    judged_by_llm: bool
    created_at: datetime


class JobsPage(BaseSchema):
    items: list[ClassificationSummary]
    total: int
    page: int
    page_size: int


class JobDetail(BaseSchema):
    job_id: str
    filename: str
    status: str
    created_at: datetime

    @classmethod
    def from_model(cls, job: Job) -> "JobDetail":
        return cls(
            job_id=job.job_id,
            filename=job.filename,
            status=job.status,
            created_at=job.created_at,
        )


class EnrichedRecordSchema(BaseSchema):
    cleaned_text: str
    raw_text: str | None
    entities: dict[str, object]
    metadata: dict[str, object]

    @classmethod
    def from_model(cls, record: EnrichedRecord) -> "EnrichedRecordSchema":
        return cls(
            cleaned_text=record.cleaned_text,
            raw_text=record.raw_text,
            entities=record.entities,
            metadata=record.metadata_,
        )


class ClassificationRecordSchema(BaseSchema):
    label: str | None
    confidence: float
    all_scores: dict[str, object]
    second_opinion_label: str | None
    second_opinion_confidence: float
    classifier_disagreement: bool
    ood_metrics: dict[str, object] | None
    svm_scores: dict[str, object]
    svm_agrees_with_prediction: bool
    review_route: str
    smells: list[str]
    risk_score: int
    smell_review_suggested: bool
    foreign_municipality: str | None
    judged_by_llm: bool
    judge_final_label: str | None
    judge_reasoning: str | None
    stored_path: str | None
    human_overridden: bool

    @classmethod
    def from_model(cls, record: ClassificationRecord) -> "ClassificationRecordSchema":
        return cls(
            label=record.label,
            confidence=record.confidence,
            all_scores=record.all_scores,
            second_opinion_label=record.second_opinion_label,
            second_opinion_confidence=record.second_opinion_confidence,
            classifier_disagreement=record.classifier_disagreement,
            ood_metrics=record.ood_metrics,
            svm_scores=record.svm_scores,
            svm_agrees_with_prediction=record.svm_agrees_with_prediction,
            review_route=record.review_route,
            smells=record.smells,
            risk_score=record.risk_score,
            smell_review_suggested=record.smell_review_suggested,
            foreign_municipality=record.foreign_municipality,
            judged_by_llm=record.judged_by_llm,
            judge_final_label=record.judge_final_label,
            judge_reasoning=record.judge_reasoning,
            stored_path=record.stored_path,
            human_overridden=record.human_overridden,
        )


class JobDetailResponse(BaseSchema):
    job: JobDetail
    enriched: EnrichedRecordSchema | None
    classification: ClassificationRecordSchema | None
    audit: list[AuditRecordSchema]

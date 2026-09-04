from typing import Annotated

from fastapi import APIRouter, Depends

from classiflow.api.dependencies import (
    CurrentUser,
    get_audit_service,
    get_classification_record_repo,
    get_current_user,
    get_job_repo,
    get_routing,
)
from classiflow.api.routes.classification.schemas import (
    ClassificationDecisionRequest,
    ReviewQueueItem,
)
from classiflow.classification.bert.ood_scorer import OodMetrics
from classiflow.classification.domain.results import RoutingInput
from classiflow.classification.domain.review_route import ReviewRoute
from classiflow.classification.exceptions import (
    ClassificationNotInReviewError,
    ClassificationRecordNotFoundError,
)
from classiflow.classification.nodes.routing import RoutingNode
from classiflow.database.repositories.audit import AuditDetail
from classiflow.domain.repositories.classification_record import IClassificationRecordRepository
from classiflow.domain.repositories.job import IJobRepository
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService
from classiflow.services.job.exceptions import JobNotFoundError
from classiflow.services.metrics.domain import AccuracyReport
from classiflow.services.metrics.service import MetricsService

router = APIRouter(
    prefix="/classification", tags=["classification"], dependencies=[Depends(get_current_user)]
)


@router.get("/review-queue")
async def review_queue(
    classification_repo: Annotated[
        IClassificationRecordRepository, Depends(get_classification_record_repo)
    ],
) -> list[ReviewQueueItem]:
    records = await classification_repo.list_needing_human_review()
    return [ReviewQueueItem.from_model(r) for r in records]


@router.get("/metrics")
async def accuracy_metrics(
    classification_repo: Annotated[
        IClassificationRecordRepository, Depends(get_classification_record_repo)
    ],
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
) -> AccuracyReport:
    return await MetricsService(classification_repo, job_repo).accuracy_report()


@router.post("/{job_id}/decision")
async def submit_classification_decision(
    job_id: str,
    body: ClassificationDecisionRequest,
    current_user: CurrentUser,
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    classification_repo: Annotated[
        IClassificationRecordRepository, Depends(get_classification_record_repo)
    ],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    routing: Annotated[RoutingNode, Depends(get_routing)],
) -> None:
    record = await classification_repo.find_by_job_id(job_id)
    if record is None:
        raise ClassificationRecordNotFoundError(job_id)
    if record.review_route != ReviewRoute.HUMAN_REVIEW:
        raise ClassificationNotInReviewError(job_id, record.review_route)

    job = await job_repo.find_by_job_id(job_id)
    if job is None:
        # Defensive only -- ClassificationRecord.job_id FK (ondelete="CASCADE") means a
        # record can't outlive its Job in practice; this satisfies mypy's None-check on
        # job.filename below without asserting away a real (if unreachable) failure mode.
        raise JobNotFoundError(job_id)

    await audit_service.record(
        job_id,
        "classification_decision",
        "human_decision",
        detail=AuditDetail.model_validate({
            "label": body.label,
            "notes": body.notes,
            "decided_by": current_user.email,
        }),
    )

    ood_metrics = record.ood_metrics
    routing_input = RoutingInput(
        job_id=job_id,
        filename=job.filename,
        enriched_id=record.enriched_id,
        label=body.label,
        confidence=record.confidence,
        all_scores=record.all_scores,
        second_opinion_label=record.second_opinion_label,
        second_opinion_confidence=record.second_opinion_confidence,
        classifier_disagreement=record.classifier_disagreement,
        ood_metrics=OodMetrics.model_validate(ood_metrics) if ood_metrics is not None else None,
        svm_scores=record.svm_scores,
        svm_agrees_with_prediction=record.svm_agrees_with_prediction,
        review_route=ReviewRoute.ACCEPT,
        smells=record.smells,
        risk_score=record.risk_score,
        smell_review_suggested=record.smell_review_suggested,
        foreign_municipality=record.foreign_municipality,
        judged_by_llm=record.judged_by_llm,
        human_overridden=True,
        # record.label still holds the machine's prediction; routing.run() below
        # overwrites it. `or` keeps the first prediction across repeated overrides.
        original_label=record.original_label or record.label,
        expected_label=record.expected_label,
        # Pass the stored value through; RoutingNode only writes it when unset, so this
        # resolution cannot rewrite the machine's original route.
        machine_review_route=record.machine_review_route,
    )
    ctx = JobContext(job_id=job_id, filename=job.filename)
    await routing.run(ctx, routing_input)

"""Pure-logic review-route decision -- spec Decision 5, adapted from
tasks/plan_stage4.md's decide_review_route. ReviewRoute.LLM_JUDGE is a legitimate
transient value here; only Routing (Task 14) enforces the two-terminal-state rule."""

from classiflow.classification.config_classification import (
    ClassificationConfig,
    get_classification_config,
)
from classiflow.classification.domain.categories import DocumentCategory
from classiflow.classification.domain.review_route import ReviewRoute
from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService


class ConfidenceGateNode(BaseNode):
    @property
    def name(self) -> str:
        return "classification_confidence_gate"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        config: ClassificationConfig | None = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.config: ClassificationConfig = (
            config if config is not None else get_classification_config()
        )

    async def run(
        self,
        ctx: JobContext,
        *,
        primary_label: str,
        confidence: float,
        foreign_municipality: str | None,
        classifier_disagreement: bool,
        risk_score: int,
    ) -> ReviewRoute:
        start = await self._emit_started(ctx)
        route = self.decide(
            primary_label=primary_label,
            confidence=confidence,
            foreign_municipality=foreign_municipality,
            classifier_disagreement=classifier_disagreement,
            risk_score=risk_score,
        )
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "review_route": route.value,
            }),
        )
        return route

    def forces_human_review(
        self,
        *,
        primary_label: str,
        foreign_municipality: str | None,
        classifier_disagreement: bool,
        risk_score: int,
    ) -> bool:
        # Any of these means the final route is HUMAN_REVIEW no matter what the judge
        # concludes -- the coordinator's _judge_review_route reads this same check to
        # decide whether to trust JudgeOutput.accept or force human review regardless
        # of it. Routing such cases to LLM_JUDGE first (see decide() below) still runs
        # the judge for every flagged document -- its verdict/reasoning is persisted as
        # advisory signal for the human reviewer, it just never changes the outcome.
        return (
            classifier_disagreement
            or risk_score > self.config.smell_review_risk_threshold
            or foreign_municipality is not None
            or primary_label == DocumentCategory.OTRO.value
        )

    def decide(
        self,
        *,
        primary_label: str,
        confidence: float,
        foreign_municipality: str | None,
        classifier_disagreement: bool,
        risk_score: int,
    ) -> ReviewRoute:
        if self.forces_human_review(
            primary_label=primary_label,
            foreign_municipality=foreign_municipality,
            classifier_disagreement=classifier_disagreement,
            risk_score=risk_score,
        ):
            return ReviewRoute.LLM_JUDGE
        if confidence >= self.config.confidence_threshold:
            return ReviewRoute.ACCEPT
        return ReviewRoute.LLM_JUDGE

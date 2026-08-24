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
    ) -> ReviewRoute:
        start = await self._emit_started(ctx)
        route = self.decide(
            primary_label=primary_label,
            confidence=confidence,
            foreign_municipality=foreign_municipality,
            classifier_disagreement=classifier_disagreement,
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

    def decide(
        self,
        *,
        primary_label: str,
        confidence: float,
        foreign_municipality: str | None,
        classifier_disagreement: bool,
    ) -> ReviewRoute:
        if foreign_municipality is not None:
            return ReviewRoute.HUMAN_REVIEW
        if primary_label == DocumentCategory.OTRO.value:
            return ReviewRoute.HUMAN_REVIEW
        if classifier_disagreement:
            return ReviewRoute.LLM_JUDGE
        if confidence >= self.config.confidence_threshold:
            return ReviewRoute.ACCEPT
        return ReviewRoute.LLM_JUDGE

"""Pure-logic review-route decision -- spec Decision 5, adapted from
tasks/plan_stage4.md's decide_review_route. "llm_judge" is a legitimate transient
value here; only Routing (Task 14) enforces the two-terminal-state rule."""

from classiflow.classification.config_classification import (
    ClassificationConfig,
    get_classification_config,
)
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
        confidence: float,
        foreign_municipality: str | None,
        classifier_disagreement: bool,
    ) -> str:
        start = await self._emit_started(ctx)
        route = self.decide(
            confidence=confidence,
            foreign_municipality=foreign_municipality,
            classifier_disagreement=classifier_disagreement,
        )
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({"filename": ctx.filename, "review_route": route}),
        )
        return route

    def decide(
        self,
        *,
        confidence: float,
        foreign_municipality: str | None,
        classifier_disagreement: bool,
    ) -> str:
        if foreign_municipality is not None or classifier_disagreement:
            return "human_review"
        if confidence >= self.config.confidence_threshold:
            return "accept"
        return "llm_judge"

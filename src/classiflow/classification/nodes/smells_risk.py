"""Pure-logic smell/risk-score computation -- spec Decision 5's weights table,
risk_score = sum(weight of fired smells), smell_review_suggested = risk_score >
config.smell_review_risk_threshold."""

from classiflow.classification.config_classification import (
    ClassificationConfig,
    get_classification_config,
)
from classiflow.classification.domain.results import SmellsRiskResult
from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_SMELL_WEIGHTS = {
    "unreadable_document": 3,
    "classifier_disagreement": 3,
    "foreign_municipality": 2,
    "low_svm_margin": 2,
    "low_confidence": 1,
}


class SmellsRiskNode(BaseNode):
    @property
    def name(self) -> str:
        return "classification_smells_risk"

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
        cleaned_text: str,
        confidence: float,
        classifier_disagreement: bool,
        foreign_municipality: str | None,
        svm_agrees_with_prediction: bool,
    ) -> SmellsRiskResult:
        start = await self._emit_started(ctx)
        result = self.compute(
            cleaned_text=cleaned_text,
            confidence=confidence,
            classifier_disagreement=classifier_disagreement,
            foreign_municipality=foreign_municipality,
            svm_agrees_with_prediction=svm_agrees_with_prediction,
        )
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "smells": result.smells,
                "risk_score": result.risk_score,
                "smell_review_suggested": result.smell_review_suggested,
            }),
        )
        return result

    def compute(
        self,
        *,
        cleaned_text: str,
        confidence: float,
        classifier_disagreement: bool,
        foreign_municipality: str | None,
        svm_agrees_with_prediction: bool,
    ) -> SmellsRiskResult:
        smells: list[str] = []
        if not cleaned_text.strip():
            smells.append("unreadable_document")
        if classifier_disagreement:
            smells.append("classifier_disagreement")
        if foreign_municipality is not None:
            smells.append("foreign_municipality")
        # ponytail: reuses svm_agrees_with_prediction (already in state) rather than a
        # numeric SVM-margin threshold neither spec pins a value for -- see this task's
        # description.
        if not svm_agrees_with_prediction:
            smells.append("low_svm_margin")
        if confidence < self.config.confidence_threshold:
            smells.append("low_confidence")

        risk_score = sum(_SMELL_WEIGHTS[s] for s in smells)
        return SmellsRiskResult(
            smells=smells,
            risk_score=risk_score,
            smell_review_suggested=risk_score > self.config.smell_review_risk_threshold,
        )

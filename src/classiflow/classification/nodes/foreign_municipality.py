from classiflow.classification.bert.text_cleaning import detect_foreign_municipality
from classiflow.classification.config_classification import (
    ClassificationConfig,
    get_classification_config,
)
from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService


class ForeignMunicipalityNode(BaseNode):
    @property
    def name(self) -> str:
        return "classification_foreign_municipality"

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

    async def run(self, ctx: JobContext, cleaned_text: str) -> str | None:
        start = await self._emit_started(ctx)
        result = self.detect(cleaned_text)
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "foreign_municipality": result,
            }),
        )
        return result

    def detect(self, cleaned_text: str) -> str | None:
        if not self.config.foreign_municipality_enabled:
            return None
        match = detect_foreign_municipality(cleaned_text, self.config)
        return match.name if match is not None else None

from classiflow.classification.domain.results import RoutingInput, RoutingResult
from classiflow.classification.domain.review_route import ReviewRoute
from classiflow.database.models import ClassificationRecord
from classiflow.database.repositories.audit import AuditDetail
from classiflow.domain.repositories.classification_record import IClassificationRecordRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService
from classiflow.storage.document_storage import IDocumentStorage

_HUMAN_REVIEW_SUBDIRECTORY = "review/human_review"


class RoutingNode(BaseNode):
    @property
    def name(self) -> str:
        return "classification_routing"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        storage: IDocumentStorage,
        classification_repo: IClassificationRecordRepository,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.storage = storage
        self.classification_repo = classification_repo

    async def run(self, ctx: JobContext, routing_input: RoutingInput) -> RoutingResult:
        start = await self._emit_started(ctx)
        subdirectory = (
            f"classified/{routing_input.label}"
            if routing_input.review_route == ReviewRoute.ACCEPT
            else _HUMAN_REVIEW_SUBDIRECTORY
        )
        stored_path = await self.storage.move_to_final(
            routing_input.job_id, routing_input.filename, subdirectory
        )
        await self._save_record(routing_input, stored_path)
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": routing_input.filename,
                "label": routing_input.label,
                "confidence": routing_input.confidence,
                "review_route": routing_input.review_route,
                "smells": routing_input.smells,
                "risk_score": routing_input.risk_score,
                "smell_review_suggested": routing_input.smell_review_suggested,
                "stored_path": stored_path,
            }),
        )
        return RoutingResult(stored_path=stored_path)

    async def _save_record(self, routing_input: RoutingInput, stored_path: str) -> None:
        # Upsert, not always-insert -- this node is called from two places (spec
        # Decision 9): automatically, once, from the classification coordinator; and
        # again from the human-decision endpoint for a job already routed to
        # human_review. The second call updates the SAME row (new
        # label/review_route/human_overridden/stored_path) instead of inserting a
        # duplicate.
        record = await self.classification_repo.find_by_job_id(routing_input.job_id)
        if record is None:
            record = ClassificationRecord(
                job_id=routing_input.job_id, enriched_id=routing_input.enriched_id
            )
        record.enriched_id = routing_input.enriched_id
        record.label = routing_input.label
        record.confidence = routing_input.confidence
        # dict(...) widens dict[str, float] to the column's dict[str, object] -- JSON
        # serialization doesn't care about the value type, mypy's invariant dict does.
        record.all_scores = dict(routing_input.all_scores)
        record.second_opinion_label = routing_input.second_opinion_label
        record.second_opinion_confidence = routing_input.second_opinion_confidence
        record.classifier_disagreement = routing_input.classifier_disagreement
        # ClassificationRecord.ood_metrics is a JSON column (dict[str, object] | None) --
        # dump the pydantic model to a plain dict here, at the actual DB boundary,
        # rather than typing RoutingInput itself as a dict and pushing that
        # serialization concern onto whoever constructs it.
        ood_metrics = routing_input.ood_metrics
        record.ood_metrics = ood_metrics.model_dump() if ood_metrics is not None else None
        record.svm_scores = dict(routing_input.svm_scores)
        record.svm_agrees_with_prediction = routing_input.svm_agrees_with_prediction
        record.review_route = routing_input.review_route
        record.smells = routing_input.smells
        record.risk_score = routing_input.risk_score
        record.smell_review_suggested = routing_input.smell_review_suggested
        record.foreign_municipality = routing_input.foreign_municipality
        record.judged_by_llm = routing_input.judged_by_llm
        record.judge_final_label = routing_input.judge_final_label
        record.judge_reasoning = routing_input.judge_reasoning
        record.stored_path = stored_path
        record.human_overridden = routing_input.human_overridden
        record.original_label = routing_input.original_label
        # Only ever set, never cleared: the second call to this node (from the
        # human-decision endpoint) doesn't carry the corpus label, and an unconditional
        # assign would erase what the first call stored.
        if routing_input.expected_label is not None:
            record.expected_label = routing_input.expected_label
        # Write-once history: the first (machine) pass records its route; the
        # human-decision pass must not overwrite it with the resolved route.
        if record.machine_review_route is None:
            record.machine_review_route = (
                routing_input.machine_review_route or routing_input.review_route
            )
        await self.classification_repo.save(record)

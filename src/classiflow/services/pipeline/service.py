from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from fastapi import BackgroundTasks
from langgraph.graph.state import CompiledStateGraph

from classiflow.database.models import DocumentStep, EnrichedRecord, Job
from classiflow.domain.job import JobStatus, NodeEvent
from classiflow.domain.repositories import UNSET, IJobRepository, UnsetType
from classiflow.domain.repositories.document_steps import IDocumentStepsRepository
from classiflow.domain.repositories.enriched_record import IEnrichedRecordRepository
from classiflow.enrichment.config_enrichment import get_enrichment_config
from classiflow.enrichment.exceptions import EnrichmentError
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.domain import (
    ContentValidationResult,
    DuplicateControlResult,
    ExtractionResult,
    FileReceptionResult,
    FormatValidationResult,
    JobState,
)
from classiflow.ingesta.llm_provider import unload_slm
from classiflow.storage.document_storage import IDocumentStorage

if TYPE_CHECKING:
    from classiflow.classification.domain.state import ClassificationState
    from classiflow.enrichment.domain.state import EnrichmentState

_PIPELINE_NODE = "pipeline"
_NODE_NAMES = {
    "reception": "node1_file_reception",
    "format_validation": "node2_format_validation",
    "extraction": "extraction",
    "content_validation": "node3_content_validation",
    "duplicate_control": "node4_duplicate_control",
}
_StepResult = (
    FileReceptionResult
    | FormatValidationResult
    | ExtractionResult
    | ContentValidationResult
    | DuplicateControlResult
)


class PipelineService:
    def __init__(
        self,
        job_repo: IJobRepository,
        document_steps_repo: IDocumentStepsRepository,
        enriched_record_repo: IEnrichedRecordRepository,
        broadcaster: EventBroadcaster,
        coordinator: CompiledStateGraph,  # type: ignore[type-arg]
        enrichment_coordinator: CompiledStateGraph,  # type: ignore[type-arg]
        document_storage: IDocumentStorage,
        classification_coordinator: CompiledStateGraph,  # type: ignore[type-arg]
    ) -> None:
        self._job_repo = job_repo
        self._document_steps_repo = document_steps_repo
        self._enriched_record_repo = enriched_record_repo
        self._broadcaster = broadcaster
        self._coordinator = coordinator
        self._enrichment_coordinator = enrichment_coordinator
        self._document_storage = document_storage
        self._classification_coordinator = classification_coordinator

    async def start(
        self, background_tasks: BackgroundTasks, filename: str, file_bytes: bytes
    ) -> str:
        # FastAPI runs background tasks after the response is sent, so scheduling the
        # coordinator here (instead of awaiting it) can't affect ingest's response latency.
        job_id = str(uuid4())
        now = datetime.now(timezone.utc)
        # server_default only fires on a real INSERT — InMemoryJobRepository never
        # round-trips through SQL, so created_at/updated_at must be set explicitly.
        await self._job_repo.create(
            Job(job_id=job_id, filename=filename, status="started", created_at=now, updated_at=now)
        )
        background_tasks.add_task(self._run, job_id, filename, file_bytes)
        return job_id

    async def _run(self, job_id: str, filename: str, file_bytes: bytes) -> None:
        initial: JobState = {"job_id": job_id, "filename": filename, "file_bytes": file_bytes}
        final_state = cast("JobState", await self._coordinator.ainvoke(initial))

        failed_at_node = await self._persist_steps(job_id, final_state)
        await self._finalize_job(job_id, final_state, failed_at_node)

        # Gated on extraction (not final_status): jobs that later land in review still
        # need their bytes staged so Stage 4's Routing can move the real file later.
        if final_state.get("extraction") is not None:
            await self._document_storage.save_staged(job_id, filename, file_bytes)

        if final_state.get("final_status") == "accepted":
            enriched_record = await self._run_enrichment(job_id, filename, final_state)
            if enriched_record is not None:
                await self._run_classification(job_id, filename, enriched_record)

        unload_slm()

        await self._broadcaster.emit(
            NodeEvent(job_id=job_id, node=_PIPELINE_NODE, status=JobStatus.DONE)
        )

    async def _persist_steps(self, job_id: str, final_state: JobState) -> str | None:
        # Saves one DocumentStep per node the coordinator actually ran, and returns the
        # name of the node that failed, if any. The coordinator stops at the first
        # failing/reviewing node, so at most one result here ever has passed=False.
        failed_at_node: str | None = None
        for step_order, key in enumerate(_NODE_NAMES, start=1):
            result = cast("_StepResult | None", final_state.get(key))
            if result is None:
                continue
            node_name = _NODE_NAMES[key]
            await self._document_steps_repo.save_step(
                DocumentStep(
                    job_id=job_id,
                    step_order=step_order,
                    node=node_name,
                    status="passed" if result.passed else "failed",
                    passed=result.passed,
                    rejection_reason=result.rejection_reason or None,
                    detail=result.model_dump(),
                    # InMemoryDocumentStepsRepository never round-trips through SQL either.
                    timestamp=datetime.now(timezone.utc),
                )
            )
            if not result.passed:
                failed_at_node = node_name
        return failed_at_node

    async def _finalize_job(
        self, job_id: str, final_state: JobState, failed_at_node: str | None
    ) -> None:
        final_status = final_state.get("final_status", "rejected")
        # Only persist extracted text for jobs that didn't get auto-accepted -- keeps
        # storage bounded instead of retaining every successfully processed document.
        extracted_text: str | UnsetType | None = UNSET
        if final_status != "accepted":
            extracted_text = final_state.get("text") or None
        await self._job_repo.update_status(
            job_id,
            final_status,
            rejection_reason=final_state.get("rejection_reason") or None,
            failed_at_node=failed_at_node,
            review_action_needed="pending" if final_status == "review" else None,
            extracted_text=extracted_text,
        )

    async def _run_enrichment(
        self, job_id: str, filename: str, final_state: JobState
    ) -> EnrichedRecord | None:
        reception = final_state["reception"]
        content_validation = final_state["content_validation"]
        extraction = final_state["extraction"]
        initial: EnrichmentState = {
            "job_id": job_id,
            "filename": filename,
            "text": final_state["text"],
            "language": content_validation.detected_language,
            "sha256": reception.sha256,
            "stage2_extractor_used": extraction.extractor_used,
        }
        max_retries = get_enrichment_config().max_enrichment_retries
        last_error: EnrichmentError | None = None
        for _attempt in range(max_retries + 1):
            try:
                result = cast(
                    "EnrichmentState", await self._enrichment_coordinator.ainvoke(initial)
                )
                record = EnrichedRecord(
                    job_id=job_id,
                    cleaned_text=result["cleaned_text"],
                    entities=result["entities"].model_dump(),
                    metadata_=result["metadata"].model_dump(),
                )
                await self._enriched_record_repo.save(record)
            except EnrichmentError as exc:
                last_error = exc
                continue
            return record
        await self._job_repo.update_status(
            job_id,
            "review",
            rejection_reason=f"Enrichment failed after retries: {last_error}",
            review_action_needed="enrichment_failed",
            failed_at_node="enrichment",
        )
        return None

    async def _run_classification(
        self, job_id: str, filename: str, enriched_record: EnrichedRecord
    ) -> None:
        # No retry-then-review fallback here, unlike _run_enrichment -- neither this
        # spec nor the BERT spec describes one for classification failures. A raised
        # ClassificationError simply propagates out of this background task uncaught;
        # revisit if that turns out to need the same bounded-retry treatment Stage 3
        # got.
        initial: ClassificationState = {
            "job_id": job_id,
            "filename": filename,
            "cleaned_text": enriched_record.cleaned_text,
            "enriched_id": enriched_record.id,
        }
        await self._classification_coordinator.ainvoke(initial)

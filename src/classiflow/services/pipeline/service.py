import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from fastapi import BackgroundTasks
from langgraph.graph.state import CompiledStateGraph
from loguru import logger

from classiflow.classification.nodes.second_opinion import unload_bert
from classiflow.database.models import DocumentKb, DocumentStep, EnrichedRecord, Job
from classiflow.domain.job import JobStatus, NodeEvent
from classiflow.domain.repositories import (
    UNSET,
    IDocumentKbRepository,
    IJobRepository,
    UnsetType,
)
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
from classiflow.knowledge.exceptions import KnowledgeError
from classiflow.knowledge.indexing.indexer import IndexerService, IndexResult
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


def _build_document_kb(indexed: IndexResult, record: EnrichedRecord, sha256: str) -> DocumentKb:
    """Build a DocumentKb row from an indexed EnrichedRecord.

    Returns:
        Database DocumentKb model with all fields populated.
    """
    metadata = indexed.metadata.for_storage()
    return DocumentKb(
        job_id=record.job_id,
        sha256=sha256,
        filename=record.filename or "",
        doc_type=metadata.doc_type,
        number=metadata.number,
        year=metadata.year,
        chunk_count=indexed.chunk_count,
        # server_default only fires on a real INSERT -- InMemoryDocumentKbRepository
        # never round-trips through SQL, so indexed_at must be set explicitly.
        indexed_at=datetime.now(timezone.utc),
        enriched_record_id=record.id,
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
        job_semaphore: asyncio.Semaphore,
        indexer: IndexerService,
        document_kb_repo: IDocumentKbRepository,
    ) -> None:
        self._job_repo = job_repo
        self._document_steps_repo = document_steps_repo
        self._enriched_record_repo = enriched_record_repo
        self._broadcaster = broadcaster
        self._coordinator = coordinator
        self._enrichment_coordinator = enrichment_coordinator
        self._document_storage = document_storage
        self._classification_coordinator = classification_coordinator
        self._job_semaphore = job_semaphore
        self._indexer = indexer
        self._document_kb_repo = document_kb_repo

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
            Job(job_id=job_id, filename=filename, status="queued", created_at=now, updated_at=now)
        )
        background_tasks.add_task(self._run, job_id, filename, file_bytes)
        return job_id

    async def _run(self, job_id: str, filename: str, file_bytes: bytes) -> None:
        async with self._job_semaphore:
            await self._job_repo.update_status(job_id, "processing")
            # _run is a FastAPI BackgroundTask -- it keeps writing through this same
            # DB session long after the request that resolved it has already returned
            # its response. Every repo here only flush()es (see IJobRepository.commit's
            # docstring); without an explicit commit, nothing becomes visible to any
            # other request's session until get_session's teardown fires at the end of
            # this whole background task -- i.e. the job silently vanishes from
            # GET /pipeline/jobs?status=running for its entire multi-minute run instead
            # of ever showing as "processing". Committing at each phase boundary below
            # makes the job (and every audit record a node wrote via the same shared
            # session) visible incrementally instead of all at once at the very end.
            await self._job_repo.commit()
            await self._broadcaster.emit(
                NodeEvent(job_id=job_id, node=_PIPELINE_NODE, status=JobStatus.PROCESSING)
            )
            initial: JobState = {"job_id": job_id, "filename": filename, "file_bytes": file_bytes}
            final_state = cast("JobState", await self._coordinator.ainvoke(initial))

            failed_at_node = await self._persist_steps(job_id, final_state)
            await self._finalize_job(job_id, final_state, failed_at_node)
            await self._job_repo.commit()

            # Gated on extraction (not final_status): jobs that later land in review
            # still need their bytes staged so Stage 4's Routing can move the real file
            # later.
            if final_state.get("extraction") is not None:
                await self._document_storage.save_staged(job_id, filename, file_bytes)

            if final_state.get("final_status") == "accepted":
                # Stage 1 passing doesn't mean the job is done -- enrichment and
                # classification still run. _finalize_job left status at "processing"
                # (not "accepted") for exactly this reason: a terminal status here would
                # make GET /pipeline/jobs?status=running drop the job from the Processing
                # page while it's still mid-pipeline.
                enriched_record = await self._run_enrichment(job_id, filename, final_state)
                await self._job_repo.commit()
                if enriched_record is not None:
                    await self._run_classification(job_id, filename, enriched_record)
                    await self._job_repo.update_status(job_id, "classified")
                    await self._job_repo.commit()

            unload_slm()
            # BETO stays on CUDA for the process lifetime otherwise, shrinking the
            # budget below what the next job's GGUF load needs on an 8GB card.
            unload_bert()

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
        # "accepted" is a Stage 1 outcome, not a terminal job status -- enrichment and
        # classification still run afterward (see _run above). Writing "accepted" here
        # would make the job vanish from GET /pipeline/jobs?status=running mid-pipeline;
        # staying at "processing" keeps it visible until _run reaches a real terminal
        # status ("classified") or enrichment fails it into "review".
        job_status = "processing" if final_status == "accepted" else final_status
        await self._job_repo.update_status(
            job_id,
            job_status,
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
                    raw_text=final_state["text"],
                    filename=filename,
                    sha256=reception.sha256,
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

    async def index_enriched_record(
        self, record: EnrichedRecord, filename: str, sha256: str
    ) -> bool:
        """Index one enriched record's cleaned text into the knowledge base.

        Non-fatal by design: a KnowledgeError here must never fail the job or the
        caller (the automatic post-enrichment hook, or the synchronize-kb endpoint).

        Returns:
            Whether a DocumentKb row was written.
        """
        try:
            indexed = await self._indexer.index(
                record.job_id, filename, sha256, record.cleaned_text, record.entities
            )
        except KnowledgeError as exc:
            logger.warning("Knowledge indexing failed for job {}: {}", record.job_id, exc)
            return False
        if indexed.chunk_count == 0:
            return False
        await self._document_kb_repo.save(_build_document_kb(indexed, record, sha256))
        return True

    async def synchronize_kb(self) -> tuple[list[str], int]:
        """Index every EnrichedRecord that has no DocumentKb row yet.

        Returns:
            Tuple of (job_ids successfully indexed, count skipped or failed).
        """
        unindexed = await self._enriched_record_repo.find_unindexed()
        indexed_job_ids: list[str] = []
        skipped = 0
        for record in unindexed:
            # record.job_id is a unique UUID: falling back to "" here instead would
            # collide every no-identity record onto the same sha256, overwriting both
            # their document_kb row and their Chroma chunk ids (Chunk.make_id keys off
            # sha256) in place of each other.
            was_indexed = await self.index_enriched_record(
                record, record.filename or "", record.sha256 or record.job_id
            )
            if was_indexed:
                indexed_job_ids.append(record.job_id)
            else:
                skipped += 1
        return indexed_job_ids, skipped

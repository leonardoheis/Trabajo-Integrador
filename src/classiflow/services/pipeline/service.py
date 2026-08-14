from datetime import datetime, timezone
from typing import cast
from uuid import uuid4

from fastapi import BackgroundTasks
from langgraph.graph.state import CompiledStateGraph

from classiflow.database.models import DocumentStep, Job
from classiflow.domain.job import JobStatus, NodeEvent
from classiflow.domain.repositories import UNSET, IJobRepository, UnsetType
from classiflow.domain.repositories.document_steps import IDocumentStepsRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.domain.results import (
    ContentValidationResult,
    DuplicateControlResult,
    FileReceptionResult,
    FormatValidationResult,
)
from classiflow.ingesta.domain.state import JobState
from classiflow.ingesta.llm_provider import unload_slm

_PIPELINE_NODE = "pipeline"
_NODE_NAMES = {
    "reception": "node1_file_reception",
    "format_validation": "node2_format_validation",
    "content_validation": "node3_content_validation",
    "duplicate_control": "node4_duplicate_control",
}
_StepResult = (
    FileReceptionResult | FormatValidationResult | ContentValidationResult | DuplicateControlResult
)


class PipelineService:
    def __init__(
        self,
        job_repo: IJobRepository,
        document_steps_repo: IDocumentStepsRepository,
        broadcaster: EventBroadcaster,
        coordinator: CompiledStateGraph,  # type: ignore[type-arg]
    ) -> None:
        self._job_repo = job_repo
        self._document_steps_repo = document_steps_repo
        self._broadcaster = broadcaster
        self._coordinator = coordinator

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

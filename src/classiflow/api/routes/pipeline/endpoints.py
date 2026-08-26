from collections.abc import AsyncGenerator
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile
from fastapi.responses import StreamingResponse

from classiflow.api.dependencies import (
    CurrentUser,
    CurrentUserFromQueryToken,
    get_audit_repo,
    get_current_user,
    get_document_steps_repo,
    get_job_repo,
    get_job_service,
    get_pipeline_service,
)
from classiflow.api.routes.pipeline.schemas import (
    BulkIngestResponse,
    DecisionRequest,
    DocumentStepSchema,
    IngestResponse,
    JobSummary,
    ReviewQueueItem,
    SynchronizeKbResponse,
    TimelineEntry,
)
from classiflow.domain.repositories.document_steps import IDocumentStepsRepository
from classiflow.domain.repositories.job import IJobRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.injections.production import Container
from classiflow.services.audit.repository import IAuditRepository
from classiflow.services.job.exceptions import JobNotFoundError
from classiflow.services.job.service import JobService
from classiflow.services.pipeline.service import PipelineService

router = APIRouter(prefix="/pipeline", tags=["pipeline"], dependencies=[Depends(get_current_user)])

# Separate router, same prefix, deliberately WITHOUT the router-level
# Depends(get_current_user) gate above -- EventSource can't send an Authorization
# header, so its one route (pipeline_events) authenticates via CurrentUserFromQueryToken
# instead, applied per-route rather than at the router level.
sse_router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/ingest", status_code=202)
async def ingest(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    pipeline: Annotated[PipelineService, Depends(get_pipeline_service)],
) -> IngestResponse:
    filename = file.filename or "unknown"
    file_bytes = await file.read()
    job_id = await pipeline.start(background_tasks, filename, file_bytes)
    return IngestResponse(job_id=job_id)


@router.post("/ingest-bulk", status_code=202)
async def ingest_bulk(
    files: list[UploadFile],
    background_tasks: BackgroundTasks,
    pipeline: Annotated[PipelineService, Depends(get_pipeline_service)],
) -> BulkIngestResponse:
    job_ids = []
    for file in files:
        filename = file.filename or "unknown"
        file_bytes = await file.read()
        job_ids.append(await pipeline.start(background_tasks, filename, file_bytes))
    return BulkIngestResponse(job_ids=job_ids)


@router.post("/synchronize-kb", status_code=200)
async def synchronize_kb(
    pipeline: Annotated[PipelineService, Depends(get_pipeline_service)],
) -> SynchronizeKbResponse:
    indexed_job_ids, skipped_count = await pipeline.synchronize_kb()
    return SynchronizeKbResponse(indexed_job_ids=indexed_job_ids, skipped_count=skipped_count)


@router.get("/review-queue")
async def review_queue(
    job_service: Annotated[JobService, Depends(get_job_service)],
) -> list[ReviewQueueItem]:
    queue = await job_service.list_review_queue()
    return [
        ReviewQueueItem(
            job_id=job.job_id,
            filename=job.filename,
            status=job.status,
            rejection_reason=job.rejection_reason,
            created_at=job.created_at,
            document_steps=[DocumentStepSchema.from_model(s) for s in steps],
        )
        for job, steps in queue
    ]


@router.get("/jobs")
async def list_jobs(
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    status: str = "running",
) -> list[JobSummary]:
    all_jobs = await job_repo.list_all()
    if status == "running":
        jobs = [j for j in all_jobs if j.status in {"queued", "processing"}]
    else:
        jobs = all_jobs
    return [
        JobSummary(
            job_id=j.job_id,
            filename=j.filename,
            status=j.status,
            created_at=j.created_at,
            updated_at=j.updated_at,
        )
        for j in jobs
    ]


@router.get("/jobs/{job_id}/timeline")
async def job_timeline(
    job_id: str,
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    document_steps_repo: Annotated[IDocumentStepsRepository, Depends(get_document_steps_repo)],
    audit_repo: Annotated[IAuditRepository, Depends(get_audit_repo)],
) -> list[TimelineEntry]:
    if await job_repo.find_by_job_id(job_id) is None:
        raise JobNotFoundError(job_id)

    steps = await document_steps_repo.steps_for_job(job_id)
    audit_records = await audit_repo.list_for_job(job_id)

    entries = [
        TimelineEntry(
            node=s.node,
            status=s.status,
            passed=s.passed,
            detail=s.detail,
            timestamp=s.timestamp,
            duration_ms=s.duration_ms,
        )
        for s in steps
    ] + [
        TimelineEntry(
            node=a.node,
            status=a.event,
            passed=None,
            detail=a.detail,
            timestamp=a.timestamp,
            duration_ms=a.duration_ms,
        )
        for a in audit_records
    ]
    entries.sort(key=lambda e: e.timestamp)
    return entries


@sse_router.get("/{job_id}/events")
@inject
async def pipeline_events(
    job_id: str,
    current_user: CurrentUserFromQueryToken,
    job_service: Annotated[JobService, Depends(get_job_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> StreamingResponse:
    del current_user  # only used to enforce authentication
    if await job_service.get_job(job_id) is None:
        raise JobNotFoundError(job_id)

    async def _stream() -> AsyncGenerator[str, None]:
        try:
            async for event in broadcaster.subscribe(job_id):
                yield event.to_sse()
        finally:
            await broadcaster.close(job_id)

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/{job_id}/decision")
async def submit_decision(
    job_id: str,
    body: DecisionRequest,
    current_user: CurrentUser,
    job_service: Annotated[JobService, Depends(get_job_service)],
) -> None:
    await job_service.submit_decision(
        job_id, decided_by=current_user.email, decision=body.decision, notes=body.notes
    )

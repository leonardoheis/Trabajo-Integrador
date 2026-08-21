from collections.abc import AsyncGenerator
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile
from fastapi.responses import StreamingResponse

from classiflow.api.dependencies import (
    CurrentUser,
    get_current_user,
    get_job_service,
    get_pipeline_service,
)
from classiflow.api.routes.pipeline.schemas import (
    DecisionRequest,
    DocumentStepSchema,
    IngestResponse,
    ReviewQueueItem,
)
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.injections.production import Container
from classiflow.services.job.exceptions import JobNotFoundError
from classiflow.services.job.service import JobService
from classiflow.services.pipeline.service import PipelineService

router = APIRouter(prefix="/pipeline", tags=["pipeline"], dependencies=[Depends(get_current_user)])


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


@router.get("/{job_id}/events")
@inject
async def pipeline_events(
    job_id: str,
    job_service: Annotated[JobService, Depends(get_job_service)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> StreamingResponse:
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

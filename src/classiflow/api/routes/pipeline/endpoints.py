from collections.abc import AsyncGenerator
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile
from fastapi.responses import StreamingResponse

from classiflow.api.dependencies import (
    CurrentUser,
    get_current_user,
    get_document_steps_repo,
    get_human_decision_repo,
    get_job_repo,
    get_pipeline_service,
)
from classiflow.api.routes.pipeline.schemas import (
    DecisionRequest,
    DocumentStepSchema,
    IngestResponse,
    ReviewQueueItem,
)
from classiflow.database.models import HumanDecision
from classiflow.domain.repositories.document_steps import IDocumentStepsRepository
from classiflow.domain.repositories.human_decision import IHumanDecisionRepository
from classiflow.domain.repositories.job import IJobRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.injections.production import Container
from classiflow.services.pipeline.exceptions import JobNotFoundError, JobNotInReviewError
from classiflow.services.pipeline.service import PipelineService

router = APIRouter(prefix="/pipeline", tags=["pipeline"], dependencies=[Depends(get_current_user)])

_DECISION_TO_STATUS = {"accept": "accepted", "reject": "rejected", "escalate": "escalated"}


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
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    document_steps_repo: Annotated[IDocumentStepsRepository, Depends(get_document_steps_repo)],
) -> list[ReviewQueueItem]:
    jobs = [j for j in await job_repo.list_all() if j.status == "review"]
    items = []
    for job in jobs:
        steps = await document_steps_repo.steps_for_job(job.job_id)
        items.append(
            ReviewQueueItem(
                job_id=job.job_id,
                filename=job.filename,
                status=job.status,
                rejection_reason=job.rejection_reason,
                created_at=job.created_at,
                document_steps=[DocumentStepSchema.from_model(s) for s in steps],
            )
        )
    return items


@router.get("/{job_id}/events")
@inject
async def pipeline_events(
    job_id: str,
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    broadcaster: Annotated[EventBroadcaster, Depends(Provide[Container.broadcaster])],
) -> StreamingResponse:
    if await job_repo.find_by_job_id(job_id) is None:
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
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    human_decision_repo: Annotated[IHumanDecisionRepository, Depends(get_human_decision_repo)],
) -> None:
    job = await job_repo.find_by_job_id(job_id)
    if job is None:
        raise JobNotFoundError(job_id)
    if job.status != "review":
        raise JobNotInReviewError(job_id, job.status)

    await human_decision_repo.save(
        HumanDecision(
            job_id=job_id,
            decided_by=current_user.email,
            decision=body.decision,
            notes=body.notes,
        )
    )
    await job_repo.update_status(job_id, _DECISION_TO_STATUS[body.decision])

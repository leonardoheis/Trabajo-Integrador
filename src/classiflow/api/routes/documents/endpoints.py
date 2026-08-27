import mimetypes
from collections.abc import Iterator
from http import HTTPStatus
from pathlib import Path
from typing import Annotated, Literal

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from classiflow.api.dependencies import (
    get_audit_repo,
    get_classification_record_repo,
    get_current_user,
    get_enriched_record_repo,
    get_job_repo,
)
from classiflow.api.routes.audit.schemas import AuditRecordSchema
from classiflow.api.routes.documents.schemas import (
    ClassificationRecordSchema,
    ClassificationSummary,
    EnrichedRecordSchema,
    JobDetail,
    JobDetailResponse,
    JobsPage,
)
from classiflow.domain.repositories.classification_record import IClassificationRecordRepository
from classiflow.domain.repositories.enriched_record import IEnrichedRecordRepository
from classiflow.domain.repositories.job import IJobRepository
from classiflow.injections.production import Container
from classiflow.services.audit.repository import IAuditRepository
from classiflow.storage.document_storage import IDocumentStorage

router = APIRouter(tags=["documents"], dependencies=[Depends(get_current_user)])

SortField = Literal["filename", "label", "confidence", "createdAt"]


def _sort_summaries(
    summaries: list[ClassificationSummary], sort: SortField, *, descending: bool
) -> None:
    # Each branch's key function returns a single, internally-comparable type (str,
    # float, or datetime) -- a single shared dict of key functions would need a
    # str | float | datetime return type that isn't safely comparable across branches,
    # which is exactly the kind of untyped escape hatch this project avoids.
    if sort == "filename":
        summaries.sort(key=lambda s: s.filename.lower(), reverse=descending)
    elif sort == "label":
        summaries.sort(key=lambda s: (s.label or "").lower(), reverse=descending)
    elif sort == "confidence":
        summaries.sort(key=lambda s: s.confidence, reverse=descending)
    else:
        summaries.sort(key=lambda s: s.created_at, reverse=descending)


@router.get("/jobs")
async def list_completed_jobs(
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    classification_repo: Annotated[
        IClassificationRecordRepository, Depends(get_classification_record_repo)
    ],
    label: str | None = None,
    review_route: Annotated[str | None, Query(alias="reviewRoute")] = None,
    page: int = 1,
    page_size: Annotated[int, Query(alias="pageSize")] = 25,
    sort: SortField | None = None,
    sort_dir: Annotated[Literal["asc", "desc"], Query(alias="sortDir")] = "asc",
) -> JobsPage:
    all_jobs = await job_repo.list_all()
    completed = [j for j in all_jobs if j.status not in {"queued", "processing"}]

    summaries = []
    for job in completed:
        record = await classification_repo.find_by_job_id(job.job_id)
        if label is not None and (record is None or record.label != label):
            continue
        if review_route is not None and (record is None or record.review_route != review_route):
            continue
        summaries.append(
            ClassificationSummary(
                job_id=job.job_id,
                filename=job.filename,
                status=job.status,
                label=record.label if record else None,
                review_route=record.review_route if record else "n/a",
                confidence=record.confidence if record else 0.0,
                judged_by_llm=record.judged_by_llm if record else False,
                created_at=job.created_at,
            )
        )

    if sort is not None:
        _sort_summaries(summaries, sort, descending=sort_dir == "desc")

    total = len(summaries)
    start = (page - 1) * page_size
    page_items = summaries[start : start + page_size]
    return JobsPage(items=page_items, total=total, page=page, page_size=page_size)


@router.get("/jobs/{job_id}/detail")
async def job_detail(
    job_id: str,
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    enriched_repo: Annotated[IEnrichedRecordRepository, Depends(get_enriched_record_repo)],
    classification_repo: Annotated[
        IClassificationRecordRepository, Depends(get_classification_record_repo)
    ],
    audit_repo: Annotated[IAuditRepository, Depends(get_audit_repo)],
) -> JobDetailResponse:
    job = await job_repo.find_by_job_id(job_id)
    if job is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"No job {job_id}")

    enriched = await enriched_repo.find_by_job_id(job_id)
    classification = await classification_repo.find_by_job_id(job_id)
    audit_records = await audit_repo.list_for_job(job_id)

    return JobDetailResponse(
        job=JobDetail.from_model(job),
        enriched=EnrichedRecordSchema.from_model(enriched) if enriched else None,
        classification=(
            ClassificationRecordSchema.from_model(classification) if classification else None
        ),
        audit=[AuditRecordSchema.from_model(a) for a in audit_records],
    )


@router.get("/documents/{job_id}/file")
@inject
async def document_file(
    job_id: str,
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    document_storage: Annotated[IDocumentStorage, Depends(Provide[Container.document_storage])],
) -> StreamingResponse:
    if await job_repo.find_by_job_id(job_id) is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"No job {job_id}")

    current_path = await document_storage.find_current_path(job_id)
    if current_path is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail=f"No stored file for job {job_id}"
        )
    file_path = Path(current_path)
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

    def _iter_file() -> Iterator[bytes]:
        with file_path.open("rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(_iter_file(), media_type=content_type)

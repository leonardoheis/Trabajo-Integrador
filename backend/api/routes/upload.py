from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from pydantic import BaseModel

from agents import ingestion_agent, orchestrator
from models import AuditEntry, JobStatus
from storage import append_audit, create_job, update_job

logger = logging.getLogger(__name__)

router = APIRouter()


class UploadResponse(BaseModel):
    job_id: str
    filename: str
    status: str


@router.post("/upload", response_model=UploadResponse, status_code=202)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
) -> UploadResponse:
    """Accept a document upload and immediately return a job_id.

    Processing happens asynchronously in a background task.
    """
    filename = file.filename or "unknown"

    # Validate format early before creating the job
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    from agents.ingestion_agent import SUPPORTED_FORMATS
    if ext not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file format '.{ext}'. "
                f"Accepted: {', '.join(sorted(SUPPORTED_FORMATS))}"
            ),
        )

    job = await create_job(filename)
    await append_audit(
        AuditEntry(job_id=job.id, event="job_created", details={"filename": filename})
    )

    # Read file bytes here (before background task) so the UploadFile stream
    # is not closed when the background task runs.
    file_bytes = await file.read()

    background_tasks.add_task(_process_document, job.id, filename, file_bytes)

    logger.info("Job %s created for file '%s'.", job.id, filename)
    return UploadResponse(job_id=job.id, filename=filename, status=job.status)


async def _process_document(job_id: str, filename: str, file_bytes: bytes) -> None:
    """Background task: run ingestion + orchestration pipeline."""
    from io import BytesIO
    from starlette.datastructures import UploadFile as StarletteUploadFile

    try:
        await update_job(job_id, status=JobStatus.INGESTING)
        await append_audit(AuditEntry(job_id=job_id, event="ingestion_started"))

        # Wrap bytes back into an UploadFile-like object for the ingestion agent
        pseudo_file = StarletteUploadFile(
            filename=filename,
            file=BytesIO(file_bytes),
        )
        ingestion_result, _ = await ingestion_agent.ingest(pseudo_file)

        await update_job(job_id, status=JobStatus.ORCHESTRATING)
        await append_audit(AuditEntry(job_id=job_id, event="orchestration_started"))

        final_state = await orchestrator.orchestrate(job_id, ingestion_result, file_bytes)

        if final_state.get("error") and not final_state.get("output_path"):
            raise RuntimeError(final_state["error"])

        azure_result = final_state.get("azure_result")
        await update_job(
            job_id,
            status=JobStatus.DONE,
            result=azure_result,
            output_path=final_state.get("output_path"),
        )
        await append_audit(
            AuditEntry(
                job_id=job_id,
                event="job_completed",
                details={
                    "output_path": final_state.get("output_path"),
                    "doc_type": azure_result.doc_type if azure_result else None,
                    "confidence": final_state.get("confidence"),
                },
            )
        )
        logger.info("Job %s completed successfully.", job_id)

    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)
        await update_job(job_id, status=JobStatus.FAILED, error=str(exc))
        await append_audit(
            AuditEntry(job_id=job_id, event="job_failed", details={"error": str(exc)})
        )

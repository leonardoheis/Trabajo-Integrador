from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from models import JobRecord, JobStatus
from storage import get_job, list_jobs

logger = logging.getLogger(__name__)

router = APIRouter()

_TERMINAL_STATUSES = {JobStatus.DONE, JobStatus.FAILED}


@router.get("/jobs", response_model=list[JobRecord])
async def list_all_jobs(limit: int = 50, offset: int = 0) -> list[JobRecord]:
    """Return a paginated list of all jobs, newest first."""
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    return await list_jobs(limit=limit, offset=offset)


@router.get("/jobs/{job_id}", response_model=JobRecord)
async def get_job_detail(job_id: str) -> JobRecord:
    """Return the full detail for a single job."""
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job


@router.websocket("/jobs/{job_id}/ws")
async def job_status_stream(websocket: WebSocket, job_id: str) -> None:
    """Stream job status updates over WebSocket until the job reaches a terminal state.

    Sends one JSON message per second with the current job record.
    """
    await websocket.accept()
    logger.info("WebSocket opened for job %s.", job_id)

    try:
        while True:
            job = await get_job(job_id)
            if job is None:
                await websocket.send_json(
                    {"error": f"Job '{job_id}' not found.", "job_id": job_id}
                )
                break

            await websocket.send_json(job.model_dump(mode="json"))

            if job.status in _TERMINAL_STATUSES:
                logger.info(
                    "Job %s reached terminal status '%s', closing WebSocket.",
                    job_id,
                    job.status,
                )
                break

            await asyncio.sleep(1)  # pragma: no cover

    except WebSocketDisconnect:  # pragma: no cover
        logger.info("WebSocket disconnected for job %s.", job_id)
    except Exception as exc:  # pragma: no cover
        logger.error("WebSocket error for job %s: %s", job_id, exc)
        try:
            await websocket.send_json({"error": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:  # pragma: no cover
            pass

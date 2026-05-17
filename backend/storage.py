from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from models import AuditEntry, JobRecord, JobStatus

# In-memory stores
_jobs: dict[str, JobRecord] = {}
_audit_log: list[AuditEntry] = []

_jobs_lock = asyncio.Lock()
_audit_lock = asyncio.Lock()


async def create_job(filename: str) -> JobRecord:
    job = JobRecord(filename=filename)
    async with _jobs_lock:
        _jobs[job.id] = job
    return job


async def get_job(job_id: str) -> Optional[JobRecord]:
    async with _jobs_lock:
        return _jobs.get(job_id)


async def update_job(job_id: str, **kwargs) -> Optional[JobRecord]:
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        kwargs["updated_at"] = datetime.utcnow()
        updated = job.model_copy(update=kwargs)
        _jobs[job_id] = updated
        return updated


async def list_jobs(limit: int = 50, offset: int = 0) -> list[JobRecord]:
    async with _jobs_lock:
        all_jobs = sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)
        return all_jobs[offset : offset + limit]


async def append_audit(entry: AuditEntry) -> None:
    async with _audit_lock:
        _audit_log.append(entry)


async def get_audit_log(limit: int = 100) -> list[AuditEntry]:
    async with _audit_lock:
        return list(_audit_log[-limit:])

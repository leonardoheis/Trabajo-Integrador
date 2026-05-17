"""Tests unitarios — storage (in-memory store)."""
from __future__ import annotations

import pytest

from models.document import AuditEntry, JobStatus
from storage import append_audit, create_job, get_audit_log, get_job, list_jobs, update_job


@pytest.mark.unit
class TestJobStorage:
    async def test_create_and_retrieve_job(self) -> None:
        job = await create_job("test.pdf")
        retrieved = await get_job(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id
        assert retrieved.filename == "test.pdf"

    async def test_get_nonexistent_job_returns_none(self) -> None:
        result = await get_job("nonexistent-id-xyz")
        assert result is None

    async def test_update_job_status(self) -> None:
        job = await create_job("test.pdf")
        updated = await update_job(job.id, status=JobStatus.ANALYZING)
        assert updated is not None
        assert updated.status == JobStatus.ANALYZING

    async def test_update_job_sets_updated_at(self) -> None:
        job = await create_job("test.pdf")
        original_updated_at = job.updated_at
        updated = await update_job(job.id, status=JobStatus.DONE)
        assert updated is not None
        assert updated.updated_at >= original_updated_at

    async def test_list_jobs_includes_created(self) -> None:
        job = await create_job("file.pdf")
        jobs = await list_jobs()
        ids = [j.id for j in jobs]
        assert job.id in ids

    async def test_list_jobs_pagination(self) -> None:
        for i in range(5):
            await create_job(f"file_{i}.pdf")
        page = await list_jobs(limit=2, offset=0)
        assert len(page) == 2

    async def test_list_jobs_offset(self) -> None:
        for i in range(4):
            await create_job(f"file_{i}.pdf")
        all_jobs = await list_jobs(limit=100, offset=0)
        page = await list_jobs(limit=100, offset=2)
        assert len(page) == len(all_jobs) - 2

    async def test_list_jobs_sorted_newest_first(self) -> None:
        job_a = await create_job("first.pdf")
        job_b = await create_job("second.pdf")
        jobs = await list_jobs()
        ids = [j.id for j in jobs]
        assert ids.index(job_b.id) < ids.index(job_a.id)

    async def test_update_nonexistent_job_returns_none(self) -> None:
        result = await update_job("ghost-id", status=JobStatus.FAILED)
        assert result is None

    async def test_create_job_default_status_is_pending(self) -> None:
        job = await create_job("doc.pdf")
        assert job.status == JobStatus.PENDING


@pytest.mark.unit
class TestAuditStorage:
    async def test_append_and_retrieve_audit_entry(self) -> None:
        job = await create_job("test.pdf")
        entry = AuditEntry(job_id=job.id, event="job.created", details={"filename": "test.pdf"})
        await append_audit(entry)
        log = await get_audit_log()
        assert any(e.event == "job.created" for e in log)

    async def test_multiple_audit_entries(self) -> None:
        job = await create_job("test.pdf")
        for event in ["job.created", "job.ingesting", "job.done"]:
            await append_audit(AuditEntry(job_id=job.id, event=event, details={}))
        log = await get_audit_log()
        assert len(log) == 3

    async def test_get_audit_log_respects_limit(self) -> None:
        job = await create_job("test.pdf")
        for i in range(10):
            await append_audit(AuditEntry(job_id=job.id, event=f"event_{i}", details={}))
        log = await get_audit_log(limit=3)
        assert len(log) == 3

    async def test_get_audit_log_returns_most_recent(self) -> None:
        job = await create_job("test.pdf")
        for i in range(5):
            await append_audit(AuditEntry(job_id=job.id, event=f"event_{i}", details={}))
        log = await get_audit_log(limit=2)
        assert log[-1].event == "event_4"

import pytest

from classiflow.shared.audit.service import AuditService
from classiflow.shared.database.repositories.audit import AuditDetail, InMemoryAuditRepository

pytestmark = pytest.mark.anyio

_RECORD_VALUES = 2
_DURATION_MS = 50
_DETAIL = AuditDetail(confidence=0.95)


async def test_record_persists_to_repo() -> None:
    repo = InMemoryAuditRepository()
    service = AuditService(repo)

    await service.record("job-1", "ingestion", "started")

    records = await repo.list_for_job("job-1")
    assert len(records) == 1
    assert records[0].job_id == "job-1"
    assert records[0].agent == "ingestion"
    assert records[0].event == "started"


async def test_record_multiple_events() -> None:
    repo = InMemoryAuditRepository()
    service = AuditService(repo)

    await service.record("job-2", "ingestion", "started", duration_ms=50)
    await service.record("job-2", "classification", "passed", detail=_DETAIL)

    records = await repo.list_for_job("job-2")
    assert len(records) == _RECORD_VALUES
    assert records[0].event == "started"
    assert records[0].duration_ms == _DURATION_MS
    assert records[1].event == "passed"
    assert records[1].detail == _DETAIL.model_dump()

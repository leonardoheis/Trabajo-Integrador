"""Repository round-trip tests — all Sql* variants run against in-memory SQLite."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from classiflow.database.base import Base
from classiflow.database.models import AllowedUser, DocumentStep, HumanDecision, Job
from classiflow.database.repositories.audit import (
    InMemoryAuditRepository,
    SqlAuditRepository,
    make_audit_record,
)
from classiflow.database.repositories.document_steps import (
    InMemoryDocumentStepsRepository,
    SqlDocumentStepsRepository,
)
from classiflow.database.repositories.hash import InMemoryHashRepository, SqlHashRepository
from classiflow.database.repositories.human_decision import (
    InMemoryHumanDecisionRepository,
    SqlHumanDecisionRepository,
)
from classiflow.database.repositories.job import InMemoryJobRepository, SqlJobRepository
from classiflow.database.repositories.user import InMemoryUserRepository, SqlUserRepository

pytestmark = pytest.mark.anyio

_SHA = "a" * 64
_JOB = "job-001"
_EMAIL = "test@example.com"
_ROWS_1 = 1
_ROWS_2 = 2

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        # seed a Job row so FK constraints don't reject document_steps/human_decisions
        s.add(Job(job_id=_JOB, status="started", filename="test.pdf"))
        await s.flush()
        yield s
    await engine.dispose()


# ---------------------------------------------------------------------------
# IHashRepository
# ---------------------------------------------------------------------------


class TestSqlHashRepository:
    async def test_save_and_exists(self, session: AsyncSession) -> None:
        repo = SqlHashRepository(session)
        assert not await repo.exists(_SHA)
        await repo.save(_SHA, _JOB)
        assert await repo.exists(_SHA)

    async def test_unknown_sha_returns_false(self, session: AsyncSession) -> None:
        repo = SqlHashRepository(session)
        assert not await repo.exists("b" * 64)


class TestInMemoryHashRepository:
    async def test_save_and_exists(self) -> None:
        repo = InMemoryHashRepository()
        assert not await repo.exists(_SHA)
        await repo.save(_SHA, _JOB)
        assert await repo.exists(_SHA)

    async def test_unknown_sha_returns_false(self) -> None:
        repo = InMemoryHashRepository()
        assert not await repo.exists(_SHA)


# ---------------------------------------------------------------------------
# IAuditRepository
# ---------------------------------------------------------------------------


class TestSqlAuditRepository:
    async def test_save_and_list(self, session: AsyncSession) -> None:
        repo = SqlAuditRepository(session)
        rec = make_audit_record(_JOB, "agent1", "started", duration_ms=10)
        await repo.save(rec)
        rows = await repo.list_for_job(_JOB)
        assert len(rows) == _ROWS_1
        assert rows[0].node == "agent1"

    async def test_list_filters_by_job(self, session: AsyncSession) -> None:
        repo = SqlAuditRepository(session)
        await repo.save(make_audit_record(_JOB, "agent1", "started"))
        await repo.save(make_audit_record("other-job", "agent2", "started"))
        rows = await repo.list_for_job(_JOB)
        assert len(rows) == _ROWS_1


class TestInMemoryAuditRepository:
    async def test_save_and_list(self) -> None:
        repo = InMemoryAuditRepository()
        rec = make_audit_record(_JOB, "agent1", "started")
        await repo.save(rec)
        rows = await repo.list_for_job(_JOB)
        assert rows == [rec]

    async def test_list_filters_by_job(self) -> None:
        repo = InMemoryAuditRepository()
        r1 = make_audit_record(_JOB, "a", "ok")
        r2 = make_audit_record("other", "b", "ok")
        await repo.save(r1)
        await repo.save(r2)
        assert await repo.list_for_job(_JOB) == [r1]


# ---------------------------------------------------------------------------
# IUserRepository
# ---------------------------------------------------------------------------


def _active_user(email: str = _EMAIL) -> AllowedUser:
    return AllowedUser(email=email, is_active=True, is_blocked=False)


class TestSqlUserRepository:
    async def test_find_existing_user(self, session: AsyncSession) -> None:
        session.add(_active_user())
        await session.flush()
        repo = SqlUserRepository(session)
        user = await repo.find_by_email(_EMAIL)
        assert user is not None
        assert user.email == _EMAIL

    async def test_find_missing_returns_none(self, session: AsyncSession) -> None:
        repo = SqlUserRepository(session)
        assert await repo.find_by_email("nobody@x.com") is None

    async def test_is_allowed_active_user(self, session: AsyncSession) -> None:
        session.add(_active_user())
        await session.flush()
        repo = SqlUserRepository(session)
        assert await repo.is_allowed(_EMAIL)

    async def test_is_allowed_blocked_user(self, session: AsyncSession) -> None:
        session.add(AllowedUser(email=_EMAIL, is_active=True, is_blocked=True))
        await session.flush()
        repo = SqlUserRepository(session)
        assert not await repo.is_allowed(_EMAIL)

    async def test_is_allowed_inactive_user(self, session: AsyncSession) -> None:
        session.add(AllowedUser(email=_EMAIL, is_active=False, is_blocked=False))
        await session.flush()
        repo = SqlUserRepository(session)
        assert not await repo.is_allowed(_EMAIL)


class TestInMemoryUserRepository:
    async def test_find_and_allowed(self) -> None:
        repo = InMemoryUserRepository()
        repo.seed(_active_user())
        assert await repo.find_by_email(_EMAIL) is not None
        assert await repo.is_allowed(_EMAIL)

    async def test_blocked_not_allowed(self) -> None:
        repo = InMemoryUserRepository()
        repo.seed(AllowedUser(email=_EMAIL, is_active=True, is_blocked=True))
        assert not await repo.is_allowed(_EMAIL)

    async def test_missing_not_allowed(self) -> None:
        repo = InMemoryUserRepository()
        assert not await repo.is_allowed(_EMAIL)


# ---------------------------------------------------------------------------
# IDocumentStepsRepository
# ---------------------------------------------------------------------------


def _step(order: int, node: str = "node1") -> DocumentStep:
    return DocumentStep(
        job_id=_JOB,
        step_order=order,
        node=node,
        status="done",
        passed=True,
    )


class TestSqlDocumentStepsRepository:
    async def test_save_and_retrieve_ordered(self, session: AsyncSession) -> None:
        repo = SqlDocumentStepsRepository(session)
        await repo.save_step(_step(2))
        await repo.save_step(_step(1))
        steps = await repo.steps_for_job(_JOB)
        assert [s.step_order for s in steps] == [1, 2]

    async def test_empty_job(self, session: AsyncSession) -> None:
        repo = SqlDocumentStepsRepository(session)
        assert await repo.steps_for_job(_JOB) == []


class TestInMemoryDocumentStepsRepository:
    async def test_save_and_retrieve_ordered(self) -> None:
        repo = InMemoryDocumentStepsRepository()
        await repo.save_step(_step(3))
        await repo.save_step(_step(1))
        await repo.save_step(_step(2))
        steps = await repo.steps_for_job(_JOB)
        assert [s.step_order for s in steps] == [1, 2, 3]

    async def test_filters_by_job(self) -> None:
        repo = InMemoryDocumentStepsRepository()
        s = DocumentStep(job_id="other", step_order=1, node="a", status="done", passed=True)
        await repo.save_step(s)
        assert await repo.steps_for_job(_JOB) == []


# ---------------------------------------------------------------------------
# IHumanDecisionRepository
# ---------------------------------------------------------------------------


def _decision(decision: str = "accept") -> HumanDecision:
    return HumanDecision(
        job_id=_JOB,
        decided_by=_EMAIL,
        decision=decision,
        notes=None,
    )


class TestSqlHumanDecisionRepository:
    async def test_save_and_retrieve(self, session: AsyncSession) -> None:
        repo = SqlHumanDecisionRepository(session)
        await repo.save(_decision("accept"))
        rows = await repo.decisions_for_job(_JOB)
        assert len(rows) == _ROWS_1
        assert rows[0].decision == "accept"

    async def test_multiple_decisions_ordered(self, session: AsyncSession) -> None:
        repo = SqlHumanDecisionRepository(session)
        await repo.save(_decision("reject"))
        await repo.save(_decision("escalate"))
        rows = await repo.decisions_for_job(_JOB)
        assert len(rows) == _ROWS_2

    async def test_filters_by_job(self, session: AsyncSession) -> None:
        repo = SqlHumanDecisionRepository(session)
        await repo.save(_decision())
        assert await repo.decisions_for_job("other-job") == []


class TestInMemoryHumanDecisionRepository:
    async def test_save_and_retrieve(self) -> None:
        repo = InMemoryHumanDecisionRepository()
        d = _decision("reject")
        await repo.save(d)
        assert await repo.decisions_for_job(_JOB) == [d]

    async def test_filters_by_job(self) -> None:
        repo = InMemoryHumanDecisionRepository()
        await repo.save(_decision())
        assert await repo.decisions_for_job("other") == []


# ---------------------------------------------------------------------------
# IJobRepository
# ---------------------------------------------------------------------------


def _job(job_id: str = _JOB) -> Job:
    return Job(job_id=job_id, status="started", filename="doc.pdf")


class TestSqlJobRepository:
    async def test_create_and_find(self, session: AsyncSession) -> None:
        repo = SqlJobRepository(session)
        # The session fixture already seeds a Job with job_id=_JOB; use a different ID here.
        j = _job("sql-job-002")
        await repo.create(j)
        found = await repo.find_by_job_id("sql-job-002")
        assert found is not None
        assert found.filename == "doc.pdf"

    async def test_find_missing_returns_none(self, session: AsyncSession) -> None:
        repo = SqlJobRepository(session)
        assert await repo.find_by_job_id("nonexistent") is None

    async def test_update_status(self, session: AsyncSession) -> None:
        repo = SqlJobRepository(session)
        j = _job("sql-job-003")
        await repo.create(j)
        await repo.update_status("sql-job-003", "done")
        found = await repo.find_by_job_id("sql-job-003")
        assert found is not None
        assert found.status == "done"

    async def test_update_status_without_kwargs_preserves_existing_fields(
        self, session: AsyncSession
    ) -> None:
        repo = SqlJobRepository(session)
        await repo.create(_job("sql-job-004"))
        await repo.update_status(
            "sql-job-004",
            "review",
            rejection_reason="needs human review",
            failed_at_node="node3",
            extracted_text="garbled excerpt",
        )
        # A later status-only update (e.g. recording a human decision) must not wipe
        # the rejection_reason/failed_at_node/extracted_text audit trail set above.
        await repo.update_status("sql-job-004", "accepted")
        found = await repo.find_by_job_id("sql-job-004")
        assert found is not None
        assert found.status == "accepted"
        assert found.rejection_reason == "needs human review"
        assert found.failed_at_node == "node3"
        assert found.extracted_text == "garbled excerpt"

    async def test_list_all(self, session: AsyncSession) -> None:
        repo = SqlJobRepository(session)
        # session fixture already has one job (_JOB); create one more
        await repo.create(_job("sql-job-004"))
        rows = await repo.list_all()
        assert len(rows) >= _ROWS_2


class TestInMemoryJobRepository:
    async def test_create_and_find(self) -> None:
        repo = InMemoryJobRepository()
        await repo.create(_job())
        found = await repo.find_by_job_id(_JOB)
        assert found is not None
        assert found.status == "started"

    async def test_find_missing_returns_none(self) -> None:
        repo = InMemoryJobRepository()
        assert await repo.find_by_job_id("ghost") is None

    async def test_update_status(self) -> None:
        repo = InMemoryJobRepository()
        await repo.create(_job())
        await repo.update_status(_JOB, "classified")
        found = await repo.find_by_job_id(_JOB)
        assert found is not None
        assert found.status == "classified"

    async def test_update_status_noop_for_missing(self) -> None:
        repo = InMemoryJobRepository()
        await repo.update_status("ghost", "done")  # must not raise

    async def test_update_status_without_kwargs_preserves_existing_fields(self) -> None:
        repo = InMemoryJobRepository()
        await repo.create(_job())
        await repo.update_status(
            _JOB,
            "review",
            rejection_reason="needs human review",
            failed_at_node="node3",
            extracted_text="garbled excerpt",
        )
        await repo.update_status(_JOB, "accepted")
        found = await repo.find_by_job_id(_JOB)
        assert found is not None
        assert found.status == "accepted"
        assert found.rejection_reason == "needs human review"
        assert found.failed_at_node == "node3"
        assert found.extracted_text == "garbled excerpt"

    async def test_list_all(self) -> None:
        repo = InMemoryJobRepository()
        await repo.create(_job("a"))
        await repo.create(_job("b"))
        assert len(await repo.list_all()) == _ROWS_2

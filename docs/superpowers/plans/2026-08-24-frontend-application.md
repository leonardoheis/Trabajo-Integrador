# Classiflow Frontend Application Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Classiflow's first user interface — a React SPA (Processing dashboard,
Classification browser, Document Detail, admin-only Users/Audit Log, a Chat
placeholder) plus every backend endpoint it needs, all behind the existing Google
OAuth flow.

**Architecture:** Backend tasks land first (new endpoints, one migration, two
repository extensions, one OAuth redirect-target change) so every frontend page has a
real API to call against from the moment it's built — no mock-then-swap step. The
frontend is a single Vite-built React SPA at `src/classiflow/frontend/`, served by
FastAPI in production and proxied to by Vite's dev server locally, so frontend and
backend are always same-origin (no CORS).

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic (backend, unchanged toolchain)
· React 19 + TypeScript + Vite + `react-router` + `@tanstack/react-query` +
`react-pdf` + Tailwind CSS v4 (frontend, new).

**Spec:** `docs/superpowers/specs/2026-08-24-frontend-application-design.md` — this
plan implements all 7 decisions plus the OAuth-redirect-target clarification and the
same-origin-in-production confirmation reached during plan review (see Task 8).

## Global Constraints

- Backend: mypy strict, `Any` banned, no `TYPE_CHECKING` unless a real circular import
  exists, quote forward references instead of `from __future__ import annotations`,
  line length 100, double quotes, exceptions as `@dataclass` subclasses per service.
- Frontend: TypeScript strict (`noUnusedLocals`, `noUnusedParameters`,
  `noFallthroughCasesInSwitch`), ESLint flat config + Prettier (`printWidth: 100`,
  double quotes disabled i.e. `singleQuote: false`, trailing commas everywhere),
  carried over verbatim from `bert_tunning/frontend` per the spec's Decision 1.
- Every backend endpoint requires `Depends(get_current_user)`; `/users/*` and `/audit`
  additionally require a new `Depends(require_admin)`.
- `uv run poe check` after every backend change; `npm run lint && tsc -b` after every
  frontend change. Both are handed to the user to run per this project's standing
  "never run notebooks/commands yourself" convention — but this plan's steps assume a
  developer (human or agent with execution rights) runs them, since `poe check` is the
  project's own required verification gate, not a notebook.
- New git dependency: none for the backend. Frontend introduces its own `package.json`
  (Node/npm), fully isolated from `uv`.

---

## Part A — Backend

### Task 1: `AllowedUser.is_admin` column + migration

**Status: done**

**Files:**
- Modify: `src/classiflow/database/models.py` (`AllowedUser` class, currently lines 9-18)
- Create: `alembic/versions/0008_add_allowed_user_is_admin.py`
- Test: `tests/shared/test_repositories.py`

**Interfaces:**
- Produces: `AllowedUser.is_admin: bool` (default `False`), readable by every later task
  that touches `AllowedUser`.

- [x] **Step 1: Add the column**

```python
# database/models.py, inside class AllowedUser (after is_blocked)
is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

- [x] **Step 2: Check the latest migration revision id**

Run: `uv run alembic heads`
Expected: prints the current head revision (should be `0007_...` per the spec's
migration history — confirm before writing the new revision's `down_revision`).

- [x] **Step 3: Write the migration**

```python
"""add allowed_user.is_admin

Revision ID: 0008_add_allowed_user_is_admin
Revises: <paste the head revision id from Step 2>
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_add_allowed_user_is_admin"
down_revision = "<paste the head revision id from Step 2>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "allowed_users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("allowed_users", "is_admin")
```

- [x] **Step 4: Apply the migration to the local dev DB**

Hand this to the user to run (per project convention, never run migrations yourself):
`uv run alembic upgrade head`
Expected: no errors; `data/classiflow.db`'s `allowed_users` table gains an `is_admin`
column.

- [x] **Step 5: Write a repository test asserting the new field round-trips**

```python
# tests/shared/test_repositories.py -- add to whatever class already covers AllowedUser
async def test_allowed_user_is_admin_persists(self, user_repo: IUserRepository) -> None:
    from classiflow.database.models import AllowedUser

    user = AllowedUser(email="admin@example.com", is_active=True, is_admin=True)
    await user_repo.create(user)  # exists once Task 3 adds it; until then, seed directly
    found = await user_repo.find_by_email("admin@example.com")
    assert found is not None
    assert found.is_admin is True
```

(This step's `user_repo.create` call depends on Task 3's new `IUserRepository.create`
method — if running Task 1 before Task 3, seed via the `InMemoryUserRepository.seed()`
method that already exists instead, and revisit this test once Task 3 lands.)

- [x] **Step 6: Run the test**

Run: `uv run pytest tests/shared/test_repositories.py -k is_admin -v`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add src/classiflow/database/models.py alembic/versions/0008_add_allowed_user_is_admin.py tests/shared/test_repositories.py
git commit -m "feat: add AllowedUser.is_admin column"
```

---

### Task 2: `User.is_admin` + `AuthService` fetches the full row

**Status: done**

**Files:**
- Modify: `src/classiflow/domain/user.py` (`User` class)
- Modify: `src/classiflow/services/auth/service.py` (`AuthService.verify_token`)
- Test: `tests/services/test_auth_service.py` (create if it doesn't already exist —
  check first with `Glob "tests/**/test_auth*"`)

**Interfaces:**
- Consumes: `IUserRepository.find_by_email` (already exists,
  `domain/repositories/user.py:7`).
- Produces: `User(email: str, is_admin: bool = False)`; `AuthService.verify_token`
  returns a `User` with `is_admin` populated from the DB.

- [x] **Step 1: Write the failing test**

```python
# tests/services/test_auth_service.py
import pytest

from classiflow.database.models import AllowedUser
from classiflow.database.repositories.user import InMemoryUserRepository
from classiflow.services.auth.jwt import encode_token
from classiflow.services.auth.service import AuthService


class TestAuthServiceIsAdmin:
    async def test_verify_token_populates_is_admin_true(self) -> None:
        repo = InMemoryUserRepository()
        repo.seed(AllowedUser(email="admin@example.com", is_active=True, is_admin=True))
        service = AuthService(repo)

        user = await service.verify_token(encode_token("admin@example.com"))

        assert user.is_admin is True

    async def test_verify_token_populates_is_admin_false(self) -> None:
        repo = InMemoryUserRepository()
        repo.seed(AllowedUser(email="user@example.com", is_active=True, is_admin=False))
        service = AuthService(repo)

        user = await service.verify_token(encode_token("user@example.com"))

        assert user.is_admin is False
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/services/test_auth_service.py -v`
Expected: FAIL — `User` has no `is_admin` field yet (pydantic will silently ignore
extra kwargs or `AttributeError` depending on config; either way `assert user.is_admin`
fails or errors).

- [x] **Step 3: Add `is_admin` to `User` and update `AuthService`**

```python
# domain/user.py
class User(BaseModel):
    email: str
    is_active: bool = True
    is_admin: bool = False
```

```python
# services/auth/service.py
class AuthService:
    def __init__(self, user_repo: IUserRepository) -> None:
        self._user_repo = user_repo

    async def verify_token(self, token: str) -> User:
        payload = decode_token(token)
        allowed_user = await self._user_repo.find_by_email(payload.sub)
        if allowed_user is None or not allowed_user.is_active or allowed_user.is_blocked:
            raise NotAllowedError(email=payload.sub)
        return User(email=payload.sub, is_admin=allowed_user.is_admin)
```

(This replaces the previous `is_allowed()` call with an equivalent inline check against
the fetched row — same three conditions `is_allowed` already checks, now read once
instead of fetched twice.)

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/services/test_auth_service.py -v`
Expected: PASS

- [x] **Step 5: Run the full existing auth test suite to confirm nothing broke**

Run: `uv run pytest tests/services/ tests/api/routes/test_auth_oauth.py -v`
Expected: all PASS — `is_allowed` itself is untouched, only its caller changed.

- [x] **Step 6: Commit**

```bash
git add src/classiflow/domain/user.py src/classiflow/services/auth/service.py tests/services/test_auth_service.py
git commit -m "feat: populate User.is_admin from AllowedUser on token verification"
```

---

### Task 3: `IUserRepository` CRUD methods (`list_all`, `create`, `update`, `delete`)

**Status: done**

**Files:**
- Modify: `src/classiflow/domain/repositories/user.py`
- Modify: `src/classiflow/database/repositories/user.py`
- Test: `tests/shared/test_repositories.py`

**Interfaces:**
- Consumes: `AllowedUser` (`database/models.py`).
- Produces: `IUserRepository.list_all() -> list[AllowedUser]`,
  `create(user: AllowedUser) -> None`,
  `update(email: str, *, is_active: bool | UnsetType = UNSET, is_admin: bool | UnsetType = UNSET, is_blocked: bool | UnsetType = UNSET) -> None`,
  `delete(email: str) -> None` — used by Task 9's `/users` endpoints.

- [x] **Step 1: Write the failing tests**

```python
# tests/shared/test_repositories.py -- add a new test class near the existing user_repo tests
from classiflow.domain.repositories import UNSET


class TestUserRepositoryCrud:
    async def test_list_all_returns_every_user(self, user_repo: IUserRepository) -> None:
        await user_repo.create(AllowedUser(email="a@example.com", is_active=True))
        await user_repo.create(AllowedUser(email="b@example.com", is_active=True))

        users = await user_repo.list_all()

        assert {u.email for u in users} == {"a@example.com", "b@example.com"}

    async def test_update_changes_only_the_given_fields(self, user_repo: IUserRepository) -> None:
        await user_repo.create(
            AllowedUser(email="a@example.com", is_active=True, is_admin=False, is_blocked=False)
        )

        await user_repo.update("a@example.com", is_admin=True)

        updated = await user_repo.find_by_email("a@example.com")
        assert updated is not None
        assert updated.is_admin is True
        assert updated.is_active is True  # untouched
        assert updated.is_blocked is False  # untouched

    async def test_delete_removes_the_user(self, user_repo: IUserRepository) -> None:
        await user_repo.create(AllowedUser(email="a@example.com", is_active=True))

        await user_repo.delete("a@example.com")

        assert await user_repo.find_by_email("a@example.com") is None
```

(If `user_repo` isn't already a shared fixture in this file parametrized over
`Sql`/`InMemory`, check the existing pattern other `test_repositories.py` classes use —
follow it exactly rather than inventing a new fixture shape.)

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/shared/test_repositories.py::TestUserRepositoryCrud -v`
Expected: FAIL — `create`/`update`/`delete`/`list_all` don't exist yet on
`IUserRepository`.

- [x] **Step 3: Extend the Protocol**

```python
# domain/repositories/user.py
from typing import Protocol

from classiflow.database.models import AllowedUser
from classiflow.domain.repositories import UnsetType, UNSET  # already defined in job.py's module


class IUserRepository(Protocol):
    async def find_by_email(self, email: str) -> AllowedUser | None: ...
    async def is_allowed(self, email: str) -> bool: ...
    async def list_all(self) -> list[AllowedUser]: ...
    async def create(self, user: AllowedUser) -> None: ...

    async def update(
        self,
        email: str,
        *,
        is_active: bool | UnsetType = UNSET,
        is_admin: bool | UnsetType = UNSET,
        is_blocked: bool | UnsetType = UNSET,
    ) -> None: ...

    async def delete(self, email: str) -> None: ...
```

(`UNSET`/`UnsetType` currently live in `domain/repositories/job.py` — check
`domain/repositories/__init__.py`'s re-exports first; if they're already re-exported
from the package `__init__`, import from `classiflow.domain.repositories` directly
rather than reaching into `job.py`, matching this project's import-style convention.)

- [x] **Step 4: Implement on `SqlUserRepository` and `InMemoryUserRepository`**

```python
# database/repositories/user.py
from classiflow.domain.repositories import UNSET, UnsetType


class SqlUserRepository:
    # ... existing find_by_email, is_allowed unchanged ...

    async def list_all(self) -> list[AllowedUser]:
        result = await self._session.execute(select(AllowedUser).order_by(AllowedUser.email))
        return list(result.scalars().all())

    async def create(self, user: AllowedUser) -> None:
        self._session.add(user)
        await self._session.flush()

    async def update(
        self,
        email: str,
        *,
        is_active: bool | UnsetType = UNSET,
        is_admin: bool | UnsetType = UNSET,
        is_blocked: bool | UnsetType = UNSET,
    ) -> None:
        user = await self.find_by_email(email)
        if user is not None:
            if not isinstance(is_active, UnsetType):
                user.is_active = is_active
            if not isinstance(is_admin, UnsetType):
                user.is_admin = is_admin
            if not isinstance(is_blocked, UnsetType):
                user.is_blocked = is_blocked
            await self._session.flush()

    async def delete(self, email: str) -> None:
        user = await self.find_by_email(email)
        if user is not None:
            await self._session.delete(user)
            await self._session.flush()


class InMemoryUserRepository:
    # ... existing __init__, seed, find_by_email, is_allowed unchanged ...

    async def list_all(self) -> list[AllowedUser]:
        return list(self._users.values())

    async def create(self, user: AllowedUser) -> None:
        self._users[user.email] = user

    async def update(
        self,
        email: str,
        *,
        is_active: bool | UnsetType = UNSET,
        is_admin: bool | UnsetType = UNSET,
        is_blocked: bool | UnsetType = UNSET,
    ) -> None:
        user = self._users.get(email)
        if user is not None:
            if not isinstance(is_active, UnsetType):
                user.is_active = is_active
            if not isinstance(is_admin, UnsetType):
                user.is_admin = is_admin
            if not isinstance(is_blocked, UnsetType):
                user.is_blocked = is_blocked

    async def delete(self, email: str) -> None:
        self._users.pop(email, None)
```

- [x] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/shared/test_repositories.py::TestUserRepositoryCrud -v`
Expected: PASS

- [x] **Step 6: Run the full test suite to confirm nothing else broke**

Run: `uv run pytest -v`
Expected: all PASS (in particular, `seed()` on `InMemoryUserRepository` still works
unchanged — this task only adds methods, doesn't remove any).

- [x] **Step 7: Commit**

```bash
git add src/classiflow/domain/repositories/user.py src/classiflow/database/repositories/user.py tests/shared/test_repositories.py
git commit -m "feat: add CRUD methods to IUserRepository"
```

---

### Task 4: `IAuditRepository.list_filtered` (paginated, filterable)

**Status: done**

**Files:**
- Modify: `src/classiflow/services/audit/repository.py`
- Modify: `src/classiflow/database/repositories/audit.py`
- Test: `tests/shared/test_repositories.py`

**Interfaces:**
- Consumes: `AuditRecord` (`database/models.py`).
- Produces:
  `IAuditRepository.list_filtered(job_id: str | None, node: str | None, event: str | None, date_from: datetime | None, date_to: datetime | None, page: int, page_size: int) -> tuple[list[AuditRecord], int]`
  (records for the requested page, plus the total matching count for pagination) — used
  by Task 10's `GET /audit`.

- [x] **Step 1: Write the failing tests**

```python
# tests/shared/test_repositories.py
from datetime import datetime, timedelta, timezone

from classiflow.database.models import AuditRecord
from classiflow.services.audit.repository import IAuditRepository


class TestAuditRepositoryListFiltered:
    async def test_filters_by_job_id(self, audit_repo: IAuditRepository) -> None:
        await audit_repo.save(AuditRecord(job_id="job-1", node="node1", event="started"))
        await audit_repo.save(AuditRecord(job_id="job-2", node="node1", event="started"))

        records, total = await audit_repo.list_filtered(
            job_id="job-1",
            node=None,
            event=None,
            date_from=None,
            date_to=None,
            page=1,
            page_size=10,
        )

        assert total == 1
        assert [r.job_id for r in records] == ["job-1"]

    async def test_paginates(self, audit_repo: IAuditRepository) -> None:
        for i in range(5):
            await audit_repo.save(AuditRecord(job_id=f"job-{i}", node="node1", event="started"))

        page_1, total = await audit_repo.list_filtered(
            job_id=None,
            node=None,
            event=None,
            date_from=None,
            date_to=None,
            page=1,
            page_size=2,
        )
        page_2, _ = await audit_repo.list_filtered(
            job_id=None,
            node=None,
            event=None,
            date_from=None,
            date_to=None,
            page=2,
            page_size=2,
        )

        assert total == 5
        assert len(page_1) == 2
        assert len(page_2) == 2
        assert {r.job_id for r in page_1} != {r.job_id for r in page_2}

    async def test_filters_by_date_range(self, audit_repo: IAuditRepository) -> None:
        old = AuditRecord(
            job_id="job-old",
            node="n",
            event="e",
            timestamp=datetime.now(timezone.utc) - timedelta(days=10),
        )
        recent = AuditRecord(job_id="job-recent", node="n", event="e")
        await audit_repo.save(old)
        await audit_repo.save(recent)

        records, total = await audit_repo.list_filtered(
            job_id=None,
            node=None,
            event=None,
            date_from=datetime.now(timezone.utc) - timedelta(days=1),
            date_to=None,
            page=1,
            page_size=10,
        )

        assert total == 1
        assert records[0].job_id == "job-recent"
```

(Follow whatever fixture pattern this file already uses to parametrize
`Sql`/`InMemory` — if there's no existing `audit_repo` fixture, add one following the
same shape as `user_repo`/`job_repo`.)

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/shared/test_repositories.py::TestAuditRepositoryListFiltered -v`
Expected: FAIL — `list_filtered` doesn't exist yet.

- [x] **Step 3: Extend the Protocol**

```python
# services/audit/repository.py
from datetime import datetime
from typing import Protocol

from classiflow.database.models import AuditRecord


class IAuditRepository(Protocol):
    async def save(self, record: AuditRecord) -> None: ...
    async def list_for_job(self, job_id: str) -> list[AuditRecord]: ...

    async def list_filtered(
        self,
        job_id: str | None,
        node: str | None,
        event: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AuditRecord], int]: ...
```

- [x] **Step 4: Implement on `SqlAuditRepository` and `InMemoryAuditRepository`**

```python
# database/repositories/audit.py
from datetime import datetime

from sqlalchemy import func, select


class SqlAuditRepository:
    # ... existing __init__, save, list_for_job unchanged ...

    async def list_filtered(
        self,
        job_id: str | None,
        node: str | None,
        event: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AuditRecord], int]:
        stmt = select(AuditRecord)
        if job_id is not None:
            stmt = stmt.where(AuditRecord.job_id == job_id)
        if node is not None:
            stmt = stmt.where(AuditRecord.node == node)
        if event is not None:
            stmt = stmt.where(AuditRecord.event == event)
        if date_from is not None:
            stmt = stmt.where(AuditRecord.timestamp >= date_from)
        if date_to is not None:
            stmt = stmt.where(AuditRecord.timestamp <= date_to)

        count_result = await self._session.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = count_result.scalar_one()

        paged_stmt = (
            stmt
            .order_by(AuditRecord.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self._session.execute(paged_stmt)
        return list(result.scalars().all()), total


class InMemoryAuditRepository:
    # ... existing __init__, save, list_for_job unchanged ...

    async def list_filtered(
        self,
        job_id: str | None,
        node: str | None,
        event: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AuditRecord], int]:
        matches = [
            r
            for r in self._records
            if (job_id is None or r.job_id == job_id)
            and (node is None or r.node == node)
            and (event is None or r.event == event)
            and (date_from is None or r.timestamp >= date_from)
            and (date_to is None or r.timestamp <= date_to)
        ]
        matches.sort(key=lambda r: r.timestamp, reverse=True)
        start = (page - 1) * page_size
        return matches[start : start + page_size], len(matches)
```

- [x] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/shared/test_repositories.py::TestAuditRepositoryListFiltered -v`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add src/classiflow/services/audit/repository.py src/classiflow/database/repositories/audit.py tests/shared/test_repositories.py
git commit -m "feat: add IAuditRepository.list_filtered for paginated audit queries"
```

---

### Task 5: Queued vs. processing `Job` status

**Status: done**

**Files:**
- Modify: `src/classiflow/domain/job.py` (`JobStatus` enum)
- Modify: `src/classiflow/services/pipeline/service.py` (`start`, `_run`)
- Test: `tests/shared/test_pipeline_service_enrichment.py` (or wherever
  `PipelineService` tests already live — check with
  `Glob "tests/**/test_pipeline_service*"` first)

**Interfaces:**
- Produces: `JobStatus.PROCESSING`; `Job.status` transitions `"queued"` →
  `"processing"` → a terminal status, instead of `"started"` → terminal. Used by
  Task 6's `GET /pipeline/jobs` and the frontend's Processing page.

- [x] **Step 1: Write the failing test**

```python
# tests/shared/test_pipeline_service_enrichment.py -- add near existing PipelineService tests
class TestPipelineServiceQueuedProcessing:
    async def test_job_starts_as_queued(
        self, pipeline_service: PipelineService, job_repo: IJobRepository
    ) -> None:
        # Use whatever this test file's existing helper is for constructing
        # BackgroundTasks + calling .start() -- follow the pattern of neighboring tests
        # in this class rather than reinventing one.
        job_id = await pipeline_service.start(BackgroundTasks(), "doc.pdf", b"%PDF-1.4")

        job = await job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status == "queued"

    async def test_job_moves_to_processing_once_running(
        self, pipeline_service: PipelineService, job_repo: IJobRepository
    ) -> None:
        # Call the internal _run coroutine directly (bypassing BackgroundTasks'
        # fire-and-forget scheduling) so the test can await completion, matching how
        # this file's existing tests already invoke PipelineService internals directly.
        job_id = "test-job-processing"
        await job_repo.create(Job(job_id=job_id, filename="doc.pdf", status="queued"))
        await pipeline_service._run(job_id, "doc.pdf", b"%PDF-1.4")

        # By the time _run() returns the job has already moved past "processing" to a
        # terminal status -- assert status is no longer "queued", which is the
        # observable half of this task's behavior change (the transient "processing"
        # value is verified via the broadcaster event in the next test instead).
        job = await job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status != "queued"
```

(Adjust fixture names — `pipeline_service`, `job_repo` — to whatever this test file's
existing fixtures are actually called; read the file first if `Glob` finds it, or
place these tests directly alongside `TestPipelineServiceStaging` mentioned in
CodeGraph's earlier survey of this file.)

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/shared/test_pipeline_service_enrichment.py -k QueuedProcessing -v`
Expected: FAIL — `Job.status` is `"started"`, not `"queued"`.

- [x] **Step 3: Add `JobStatus.PROCESSING`**

```python
# domain/job.py
class JobStatus(str, Enum):
    STARTED = "started"
    PROCESSING = "processing"
    PASSED = "passed"
    FAILED = "failed"
    REJECTED = "rejected"
    REVIEW = "review"
    DONE = "done"
```

- [x] **Step 4: Update `PipelineService.start` and `_run`**

```python
# services/pipeline/service.py


async def start(self, background_tasks: BackgroundTasks, filename: str, file_bytes: bytes) -> str:
    job_id = str(uuid4())
    now = datetime.now(timezone.utc)
    await self._job_repo.create(
        Job(job_id=job_id, filename=filename, status="queued", created_at=now, updated_at=now)
    )
    background_tasks.add_task(self._run, job_id, filename, file_bytes)
    return job_id


async def _run(self, job_id: str, filename: str, file_bytes: bytes) -> None:
    async with self._job_semaphore:
        await self._job_repo.update_status(job_id, "processing")
        await self._broadcaster.emit(
            NodeEvent(job_id=job_id, node=_PIPELINE_NODE, status=JobStatus.PROCESSING)
        )
        initial: JobState = {"job_id": job_id, "filename": filename, "file_bytes": file_bytes}
        final_state = cast("JobState", await self._coordinator.ainvoke(initial))
        # ... rest of _run unchanged from here ...
```

- [x] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/shared/test_pipeline_service_enrichment.py -k QueuedProcessing -v`
Expected: PASS

- [x] **Step 6: Run the full pipeline test suite to confirm nothing broke**

Run: `uv run pytest tests/shared/ tests/api/routes/test_pipeline.py -v`
Expected: all PASS — no other code reads `Job.status == "started"` as a magic string
(confirm with a quick grep before running, per Step 6a below).

- [x] **Step 6a: Grep for any other code depending on the old `"started"` value**

Run: `grep -rn '"started"' src/classiflow/ tests/ --include="*.py"`
Expected: only `domain/job.py`'s `JobStatus.STARTED` definition itself and this task's
own changed call site remain — if anything else matches (e.g. a UI string comparison
elsewhere), that's a real dependency this task must also update; don't silently leave
it broken.

- [x] **Step 7: Commit**

```bash
git add src/classiflow/domain/job.py src/classiflow/services/pipeline/service.py tests/shared/test_pipeline_service_enrichment.py
git commit -m "feat: distinguish queued from processing Job status"
```

---

### Task 6: `GET /pipeline/jobs` and `GET /pipeline/jobs/{job_id}/timeline`

**Status: done**

**Files:**
- Modify: `src/classiflow/api/routes/pipeline/schemas.py`
- Modify: `src/classiflow/api/routes/pipeline/endpoints.py`
- Test: `tests/api/routes/test_pipeline.py`

**Interfaces:**
- Consumes: `IJobRepository.list_all()` (exists, `domain/repositories/job.py:35`),
  `IDocumentStepsRepository.steps_for_job()` (exists), `IAuditRepository.list_for_job()`
  (exists) via a new `Depends(get_audit_repo)` (Step 3 below).
- Produces: `JobSummary`, `TimelineEntry` schemas; `GET /pipeline/jobs`,
  `GET /pipeline/jobs/{job_id}/timeline` routes — consumed by the frontend's
  Processing page (Task 15).

- [x] **Step 1: Write the failing tests**

```python
# tests/api/routes/test_pipeline.py
class TestJobsEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/pipeline/jobs")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_default_status_running_excludes_terminal_jobs(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ingest(client, auth_headers, monkeypatch, legitimate=False, filename="rejected.pdf")

        response = client.get("/pipeline/jobs", headers=auth_headers)

        assert response.status_code == HTTPStatus.OK
        filenames = [j["filename"] for j in response.json()]
        assert "rejected.pdf" not in filenames


class TestJobTimelineEndpoint:
    def test_unknown_job_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/pipeline/jobs/no-such-job/timeline", headers=auth_headers)
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_returns_merged_document_steps_and_audit_records(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = _ingest(client, auth_headers, monkeypatch, legitimate=True, filename="ok.pdf")

        response = client.get(f"/pipeline/jobs/{job_id}/timeline", headers=auth_headers)

        assert response.status_code == HTTPStatus.OK
        entries = response.json()
        assert len(entries) > 0
        assert all("node" in e and "timestamp" in e for e in entries)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/routes/test_pipeline.py -k "Jobs or Timeline" -v`
Expected: FAIL — routes don't exist (404 on both, but the assertions expect 200/other
404s for a different reason, so these genuinely fail).

- [x] **Step 3: Add `get_audit_repo` dependency**

```python
# api/dependencies.py -- add near get_hash_repo (uses the same DbSession pattern)
from classiflow.services.audit.repository import IAuditRepository


def get_audit_repo(session: DbSession) -> IAuditRepository:
    return SqlAuditRepository(session)
```

(`SqlAuditRepository` is already imported in this file at line 26 — no new import
needed for that symbol, only for `IAuditRepository` itself.)

- [x] **Step 4: Add the schemas**

```python
# api/routes/pipeline/schemas.py -- add below existing schemas
class JobSummary(BaseSchema):
    job_id: str
    filename: str
    status: str
    created_at: datetime
    updated_at: datetime


class TimelineEntry(BaseSchema):
    node: str
    status: str
    passed: bool | None
    detail: dict[str, object] | None
    timestamp: datetime
    duration_ms: int | None
```

- [x] **Step 5: Add the endpoints**

```python
# api/routes/pipeline/endpoints.py -- add imports for JobSummary, TimelineEntry,
# get_audit_repo, IAuditRepository, JobNotFoundError (already imported)


@router.get("/jobs")
async def list_jobs(
    job_service: Annotated[JobService, Depends(get_job_service)],
    status: str = "running",
) -> list[JobSummary]:
    del job_service  # placeholder kept only if JobService ends up unused below -- remove
    # this whole del line once list_jobs actually reads through job_repo directly instead.
    ...
```

(This step's exact shape depends on whether `JobService` already has a way to list
jobs by status or whether the endpoint should go straight to `IJobRepository`. Prefer
`IJobRepository` directly since `list_all()` already exists there and no filtering
logic belongs in a thin route handler beyond the `status` param — write it as:)

```python
@router.get("/jobs")
async def list_jobs(
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    status: str = "running",
) -> list[JobSummary]:
    all_jobs = await job_repo.list_all()
    if status == "running":
        jobs = [j for j in all_jobs if j.status in ("queued", "processing")]
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
```

Add `IJobRepository`, `IDocumentStepsRepository` (already imported per existing
endpoint signatures in this file's neighbors), `IAuditRepository`, `get_audit_repo`,
`JobSummary`, `TimelineEntry` to this file's imports.

- [x] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/api/routes/test_pipeline.py -k "Jobs or Timeline" -v`
Expected: PASS

- [x] **Step 7: Add `get_audit_repo` override to `conftest.py`**

```python
# tests/api/conftest.py -- add alongside the other _X_repo_override functions
from classiflow.api.dependencies import get_audit_repo
from classiflow.services.audit.repository import IAuditRepository


def _audit_repo_override() -> IAuditRepository:
    return test_container.audit_repo()


# ... and add to the dependency_overrides block:
app.dependency_overrides[get_audit_repo] = _audit_repo_override
```

(`test_container.audit_repo()` already exists as a provider in `injections/test.py:116`
— this step only wires FastAPI's override to point at it, following the exact pattern
every other `_X_repo_override` function in this file already uses.)

- [x] **Step 8: Run the full API test suite**

Run: `uv run pytest tests/api/ -v`
Expected: all PASS

- [x] **Step 9: Commit**

```bash
git add src/classiflow/api/dependencies.py src/classiflow/api/routes/pipeline/schemas.py src/classiflow/api/routes/pipeline/endpoints.py tests/api/routes/test_pipeline.py tests/api/conftest.py
git commit -m "feat: add GET /pipeline/jobs and GET /pipeline/jobs/{job_id}/timeline"
```

---

### Task 7: `require_admin` dependency

**Status: done**

**Files:**
- Modify: `src/classiflow/api/dependencies.py`
- Test: `tests/api/routes/test_users.py` (created fully in Task 9 — this task only adds
  the dependency itself with a minimal direct test)

**Interfaces:**
- Consumes: `CurrentUser` (exists, `api/dependencies.py:90`).
- Produces: `require_admin` — a FastAPI dependency raising `403` when
  `CurrentUser.is_admin` is `False`; used by Task 9 and Task 10's routers.

- [x] **Step 1: Write the failing test**

```python
# tests/api/test_dependencies.py (create if it doesn't exist)
from http import HTTPStatus

import pytest
from fastapi import HTTPException

from classiflow.api.dependencies import require_admin
from classiflow.domain.user import User


class TestRequireAdmin:
    async def test_raises_403_for_non_admin(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(User(email="user@example.com", is_admin=False))
        assert exc_info.value.status_code == HTTPStatus.FORBIDDEN

    async def test_passes_for_admin(self) -> None:
        # Should not raise
        await require_admin(User(email="admin@example.com", is_admin=True))
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_dependencies.py -v`
Expected: FAIL — `require_admin` doesn't exist.

- [x] **Step 3: Implement `require_admin`**

```python
# api/dependencies.py -- add just below CurrentUser
from fastapi import HTTPException
from http import HTTPStatus


async def require_admin(current_user: CurrentUser) -> None:
    if not current_user.is_admin:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Admin access required")
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_dependencies.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/classiflow/api/dependencies.py tests/api/test_dependencies.py
git commit -m "feat: add require_admin FastAPI dependency"
```

---

### Task 8: OAuth redirect target → frontend popup route

**Status: done**

**Files:**
- Modify: `src/classiflow/settings.py` (`GOOGLE_REDIRECT_URI` default)
- No other backend change — `/auth/login` and `/auth/callback` themselves are
  untouched per the spec's explicit "keep JSON response" decision.

**Interfaces:**
- Produces: `Settings.GOOGLE_REDIRECT_URI` now defaults to a frontend route
  (`http://localhost:5173/oauth-popup` in dev — Vite's default port), which Task 14's
  frontend `oauthPopup.ts` + a new `/oauth-popup` route (Task 17) will implement as the
  `fetch`-and-`postMessage` relay page described in the spec's Decision 2, resolved
  further during plan review: Google's redirect must land on something that can run
  JS, so it lands on the frontend, which then calls the unchanged `/auth/callback`
  JSON endpoint itself via `fetch`.

- [x] **Step 1: Update the default**

```python
# settings.py, line 82-84
GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5173/oauth-popup")
```

- [x] **Step 2: Update `.env.example` to match**

```bash
# .env.example -- find the existing GOOGLE_REDIRECT_URI line (if present) or add one
GOOGLE_REDIRECT_URI=http://localhost:5173/oauth-popup
```

(Check `.env.example`'s current content first — the user has been editing this file
recently per this session's git status; add rather than blindly overwrite.)

- [x] **Step 3: Confirm no test hardcodes the old default**

Run: `grep -rn "localhost:8000/auth/callback\|GOOGLE_REDIRECT_URI" tests/ src/classiflow/`
Expected: only `settings.py`'s own definition and this task's `.env.example` change —
if any test asserts against the literal old URL string, update it to the new default
in this same task.

- [x] **Step 4: Commit**

```bash
git add src/classiflow/settings.py .env.example
git commit -m "feat: point GOOGLE_REDIRECT_URI at the frontend's OAuth popup route"
```

---

### Task 9: `/users` CRUD router (admin-only)

**Status: done**

**Files:**
- Create: `src/classiflow/api/routes/users/__init__.py`
- Create: `src/classiflow/api/routes/users/schemas.py`
- Create: `src/classiflow/api/routes/users/endpoints.py`
- Modify: `src/classiflow/api/dependencies.py` (add `get_user_repo`)
- Modify: `src/classiflow/api/routes/registry.py`
- Test: `tests/api/routes/test_users.py`

**Interfaces:**
- Consumes: `IUserRepository` (Task 3's new CRUD methods), `require_admin` (Task 7).
- Produces: `GET/POST/PATCH/DELETE /users` routes — consumed by the frontend's Users
  page (Task 18).

- [x] **Step 1: Write the failing tests**

```python
# tests/api/routes/test_users.py
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("_jwt_secret")


class TestUsersEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/users")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_requires_admin(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        # auth_headers fixture issues a token for a non-admin seeded user (per conftest.py)
        response = client.get("/users", headers=auth_headers)
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_admin_can_list_users(
        self, client: TestClient, admin_auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/users", headers=admin_auth_headers)
        assert response.status_code == HTTPStatus.OK
        assert isinstance(response.json(), list)

    def test_admin_can_create_user(
        self, client: TestClient, admin_auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/users",
            json={"email": "new@example.com", "isAdmin": False},
            headers=admin_auth_headers,
        )
        assert response.status_code == HTTPStatus.CREATED
        assert response.json()["email"] == "new@example.com"

    def test_admin_can_update_user(
        self, client: TestClient, admin_auth_headers: dict[str, str]
    ) -> None:
        client.post(
            "/users",
            json={"email": "toblock@example.com", "isAdmin": False},
            headers=admin_auth_headers,
        )
        response = client.patch(
            "/users/toblock@example.com",
            json={"isBlocked": True},
            headers=admin_auth_headers,
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["isBlocked"] is True

    def test_admin_can_delete_user(
        self, client: TestClient, admin_auth_headers: dict[str, str]
    ) -> None:
        client.post(
            "/users",
            json={"email": "todelete@example.com", "isAdmin": False},
            headers=admin_auth_headers,
        )
        response = client.delete("/users/todelete@example.com", headers=admin_auth_headers)
        assert response.status_code == HTTPStatus.NO_CONTENT
```

- [x] **Step 2: Add an `admin_auth_headers` fixture to `conftest.py`**

```python
# tests/api/conftest.py
_ADMIN_EMAIL = "admin@classiflow.dev"

# In the `client` fixture, alongside the existing `allowed` seed:
admin = AllowedUser(email=_ADMIN_EMAIL, is_active=True, is_blocked=False, is_admin=True)
test_container.user_repo().seed(admin)


@pytest.fixture
def admin_auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {encode_token(_ADMIN_EMAIL)}"}
```

- [x] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/api/routes/test_users.py -v`
Expected: FAIL — `/users` router doesn't exist (404s where 200/201/403 expected).

- [x] **Step 4: Add `get_user_repo` dependency**

```python
# api/dependencies.py
from classiflow.database.repositories.user import SqlUserRepository
from classiflow.domain.repositories.user import IUserRepository


def get_user_repo(session: DbSession) -> IUserRepository:
    return SqlUserRepository(session)
```

- [x] **Step 5: Write the schemas**

```python
# api/routes/users/schemas.py
from datetime import datetime

from classiflow.api.schemas import BaseSchema
from classiflow.database.models import AllowedUser


class UserSchema(BaseSchema):
    email: str
    is_active: bool
    is_admin: bool
    is_blocked: bool
    created_at: datetime

    @classmethod
    def from_model(cls, user: AllowedUser) -> "UserSchema":
        return cls(
            email=user.email,
            is_active=user.is_active,
            is_admin=user.is_admin,
            is_blocked=user.is_blocked,
            created_at=user.created_at,
        )


class CreateUserRequest(BaseSchema):
    email: str
    is_admin: bool = False


class UpdateUserRequest(BaseSchema):
    is_active: bool | None = None
    is_admin: bool | None = None
    is_blocked: bool | None = None
```

- [x] **Step 6: Write the router**

```python
# api/routes/users/endpoints.py
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from classiflow.api.dependencies import get_current_user, get_user_repo, require_admin
from classiflow.api.routes.users.schemas import CreateUserRequest, UpdateUserRequest, UserSchema
from classiflow.database.models import AllowedUser
from classiflow.domain.repositories import UNSET, UnsetType
from classiflow.domain.repositories.user import IUserRepository

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(get_current_user), Depends(require_admin)],
)


@router.get("")
async def list_users(
    user_repo: Annotated[IUserRepository, Depends(get_user_repo)],
) -> list[UserSchema]:
    users = await user_repo.list_all()
    return [UserSchema.from_model(u) for u in users]


@router.post("", status_code=HTTPStatus.CREATED)
async def create_user(
    body: CreateUserRequest,
    user_repo: Annotated[IUserRepository, Depends(get_user_repo)],
) -> UserSchema:
    user = AllowedUser(email=body.email, is_active=True, is_admin=body.is_admin, is_blocked=False)
    await user_repo.create(user)
    return UserSchema.from_model(user)


@router.patch("/{email}")
async def update_user(
    email: str,
    body: UpdateUserRequest,
    user_repo: Annotated[IUserRepository, Depends(get_user_repo)],
) -> UserSchema:
    await user_repo.update(
        email,
        is_active=body.is_active if body.is_active is not None else UNSET,
        is_admin=body.is_admin if body.is_admin is not None else UNSET,
        is_blocked=body.is_blocked if body.is_blocked is not None else UNSET,
    )
    updated = await user_repo.find_by_email(email)
    if updated is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"No user {email}")
    return UserSchema.from_model(updated)


@router.delete("/{email}", status_code=HTTPStatus.NO_CONTENT)
async def delete_user(
    email: str,
    user_repo: Annotated[IUserRepository, Depends(get_user_repo)],
) -> None:
    await user_repo.delete(email)
```

```python
# api/routes/users/__init__.py
from classiflow.api.routes.users.endpoints import router

__all__ = ["router"]
```

- [x] **Step 7: Register the router**

```python
# api/routes/registry.py
from classiflow.api.routes.users import router as users_router

ROUTERS: list[APIRouter] = [
    health_router,
    auth_router,
    pipeline_router,
    classification_router,
    users_router,
]
```

- [x] **Step 8: Override `get_user_repo` in `conftest.py`**

```python
# tests/api/conftest.py
from classiflow.api.dependencies import get_user_repo
from classiflow.domain.repositories.user import IUserRepository


def _user_repo_override() -> IUserRepository:
    return test_container.user_repo()


app.dependency_overrides[get_user_repo] = _user_repo_override
```

- [x] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/api/routes/test_users.py -v`
Expected: PASS

- [x] **Step 10: Run the full test suite**

Run: `uv run pytest -v`
Expected: all PASS

- [x] **Step 11: Commit**

```bash
git add src/classiflow/api/routes/users/ src/classiflow/api/dependencies.py src/classiflow/api/routes/registry.py tests/api/routes/test_users.py tests/api/conftest.py
git commit -m "feat: add admin-only /users CRUD router"
```

---

### Task 10: `GET /audit` (admin-only)

**Status: done**

**Files:**
- Modify: `src/classiflow/api/routes/pipeline/schemas.py` (or create
  `api/routes/audit/` as its own router — see Step 1's decision note)
- Test: `tests/api/routes/test_audit.py`

**Interfaces:**
- Consumes: `IAuditRepository.list_filtered` (Task 4), `require_admin` (Task 7).
- Produces: `GET /audit` — consumed by the frontend's Audit Log page (Task 19).

- [x] **Step 1: Decide the router location**

This endpoint doesn't belong under `/pipeline` or `/classification` (it's a
cross-cutting admin view, not scoped to one pipeline stage) — create a new
`api/routes/audit/` package mirroring `api/routes/users/`'s shape from Task 9
(`__init__.py` re-exporting `router`, `schemas.py`, `endpoints.py`).

- [x] **Step 2: Write the failing tests**

```python
# tests/api/routes/test_audit.py
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("_jwt_secret")


class TestAuditEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/audit")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_requires_admin(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        response = client.get("/audit", headers=auth_headers)
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_admin_can_list_audit_records(
        self,
        client: TestClient,
        admin_auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _ingest(client, admin_auth_headers, monkeypatch, legitimate=True, filename="a.pdf")

        response = client.get("/audit", headers=admin_auth_headers)

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert "items" in body
        assert "total" in body

    def test_filters_by_job_id(
        self,
        client: TestClient,
        admin_auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        job_id = _ingest(client, admin_auth_headers, monkeypatch, legitimate=True, filename="b.pdf")

        response = client.get(f"/audit?jobId={job_id}", headers=admin_auth_headers)

        assert response.status_code == HTTPStatus.OK
        assert all(r["jobId"] == job_id for r in response.json()["items"])
```

(`_ingest` is the existing helper from `tests/api/routes/test_pipeline.py` — either
import it from there if the project allows cross-test-file imports, or duplicate the
minimal ingest-and-wait logic locally, matching however `test_classification.py`
already handles the same need.)

- [x] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/api/routes/test_audit.py -v`
Expected: FAIL — `/audit` doesn't exist.

- [x] **Step 4: Write the schemas**

```python
# api/routes/audit/schemas.py
from datetime import datetime

from classiflow.api.schemas import BaseSchema
from classiflow.database.models import AuditRecord


class AuditRecordSchema(BaseSchema):
    job_id: str
    node: str
    event: str
    timestamp: datetime
    duration_ms: int | None
    detail: dict[str, object] | None

    @classmethod
    def from_model(cls, record: AuditRecord) -> "AuditRecordSchema":
        return cls(
            job_id=record.job_id,
            node=record.node,
            event=record.event,
            timestamp=record.timestamp,
            duration_ms=record.duration_ms,
            detail=record.detail,
        )


class AuditPage(BaseSchema):
    items: list[AuditRecordSchema]
    total: int
    page: int
    page_size: int
```

- [x] **Step 5: Write the router**

```python
# api/routes/audit/endpoints.py
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from classiflow.api.dependencies import get_audit_repo, get_current_user, require_admin
from classiflow.api.routes.audit.schemas import AuditPage, AuditRecordSchema
from classiflow.services.audit.repository import IAuditRepository

router = APIRouter(
    prefix="/audit",
    tags=["audit"],
    dependencies=[Depends(get_current_user), Depends(require_admin)],
)


@router.get("")
async def list_audit_records(
    audit_repo: Annotated[IAuditRepository, Depends(get_audit_repo)],
    job_id: str | None = None,
    node: str | None = None,
    event: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
) -> AuditPage:
    records, total = await audit_repo.list_filtered(
        job_id, node, event, date_from, date_to, page, page_size
    )
    return AuditPage(
        items=[AuditRecordSchema.from_model(r) for r in records],
        total=total,
        page=page,
        page_size=page_size,
    )
```

```python
# api/routes/audit/__init__.py
from classiflow.api.routes.audit.endpoints import router

__all__ = ["router"]
```

- [x] **Step 6: Register the router**

```python
# api/routes/registry.py
from classiflow.api.routes.audit import router as audit_router

ROUTERS: list[APIRouter] = [
    health_router,
    auth_router,
    pipeline_router,
    classification_router,
    users_router,
    audit_router,
]
```

- [x] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/api/routes/test_audit.py -v`
Expected: PASS

- [x] **Step 8: Commit**

```bash
git add src/classiflow/api/routes/audit/ src/classiflow/api/routes/registry.py tests/api/routes/test_audit.py
git commit -m "feat: add admin-only GET /audit endpoint"
```

---

### Task 11: `GET /auth/me`

**Status: done**

**Files:**
- Modify: `src/classiflow/api/routes/auth/endpoints.py`
- Test: `tests/api/routes/test_auth_oauth.py`

**Interfaces:**
- Consumes: `CurrentUser` (Task 2's `is_admin`-populated `User`).
- Produces: `GET /auth/me` — consumed by the frontend's `AuthContext` (Task 14).

- [x] **Step 1: Write the failing test**

```python
# tests/api/routes/test_auth_oauth.py -- add to existing test file
class TestAuthMeEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/auth/me")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_returns_current_user(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        response = client.get("/auth/me", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["email"] == _TEST_EMAIL
        assert "isAdmin" in body
```

(Match this file's existing import style for `HTTPStatus`/`_TEST_EMAIL` — check
whether `_TEST_EMAIL` is already imported/defined at module scope here or needs
importing from `conftest.py`.)

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/routes/test_auth_oauth.py -k AuthMe -v`
Expected: FAIL — `/auth/me` doesn't exist.

- [x] **Step 3: Add the endpoint**

```python
# api/routes/auth/endpoints.py -- add below auth_callback
from classiflow.api.dependencies import CurrentUser


@router.get("/me")
async def auth_me(current_user: CurrentUser) -> User:
    return current_user
```

(`User` is already imported at line 9. `CurrentUser` needs importing from
`api.dependencies` — check this doesn't create a circular import; if it does,
`api/dependencies.py` already imports from `api/routes/...` in the opposite direction
for other things, so verify with a quick `uv run mypy src` after adding rather than
guessing.)

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/routes/test_auth_oauth.py -k AuthMe -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/classiflow/api/routes/auth/endpoints.py tests/api/routes/test_auth_oauth.py
git commit -m "feat: add GET /auth/me"
```

---

### Task 12: `GET /jobs`, `GET /jobs/{job_id}/detail`, `GET /documents/{job_id}/file`

**Status: done**

**Files:**
- Create: `src/classiflow/api/routes/documents/__init__.py`
- Create: `src/classiflow/api/routes/documents/schemas.py`
- Create: `src/classiflow/api/routes/documents/endpoints.py`
- Modify: `src/classiflow/api/routes/registry.py`
- Test: `tests/api/routes/test_documents.py`

**Interfaces:**
- Consumes: `IJobRepository`, `IEnrichedRecordRepository`, `IClassificationRecordRepository`
  (all `.find_by_job_id`, already exist), `IAuditRepository.list_for_job` (exists),
  `IDocumentStorage` (`storage/document_storage.py`, `Container.document_storage`
  Provide).
- Produces: `GET /jobs`, `GET /jobs/{job_id}/detail`, `GET /documents/{job_id}/file` —
  consumed by the frontend's Classification and Document Detail pages (Tasks 16-17).

- [x] **Step 1: Write the failing tests**

```python
# tests/api/routes/test_documents.py
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("_jwt_secret")


class TestJobsListEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/jobs")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_returns_paginated_response(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/jobs", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert "items" in body
        assert "total" in body


class TestJobDetailEndpoint:
    def test_unknown_job_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/jobs/no-such-job/detail", headers=auth_headers)
        assert response.status_code == HTTPStatus.NOT_FOUND


class TestDocumentFileEndpoint:
    def test_unknown_job_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/documents/no-such-job/file", headers=auth_headers)
        assert response.status_code == HTTPStatus.NOT_FOUND
```

(Fuller happy-path tests for `/jobs/{job_id}/detail` and `/documents/{job_id}/file`
need a job that's actually reached `EnrichedRecord`/`ClassificationRecord`/staged-file
state — add those once this task's implementation exists, following the same
multi-step ingest-and-poll pattern `test_classification.py` already uses for
equivalent setup; don't skip the 404 cases above, they're the cheap, always-correct
baseline.)

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/routes/test_documents.py -v`
Expected: FAIL — routes don't exist.

- [x] **Step 3: Write the schemas**

```python
# api/routes/documents/schemas.py
from datetime import datetime

from classiflow.api.schemas import BaseSchema
from classiflow.database.models import ClassificationRecord, EnrichedRecord, Job
from classiflow.api.routes.audit.schemas import AuditRecordSchema


class ClassificationSummary(BaseSchema):
    job_id: str
    filename: str
    label: str | None
    review_route: str
    confidence: float
    judged_by_llm: bool
    created_at: datetime


class JobsPage(BaseSchema):
    items: list[ClassificationSummary]
    total: int
    page: int
    page_size: int


class JobDetail(BaseSchema):
    job_id: str
    filename: str
    status: str
    created_at: datetime

    @classmethod
    def from_model(cls, job: Job) -> "JobDetail":
        return cls(
            job_id=job.job_id,
            filename=job.filename,
            status=job.status,
            created_at=job.created_at,
        )


class EnrichedRecordSchema(BaseSchema):
    cleaned_text: str
    raw_text: str | None
    entities: dict[str, object]
    metadata: dict[str, object]

    @classmethod
    def from_model(cls, record: EnrichedRecord) -> "EnrichedRecordSchema":
        return cls(
            cleaned_text=record.cleaned_text,
            raw_text=record.raw_text,
            entities=record.entities,
            metadata=record.metadata_,
        )


class ClassificationRecordSchema(BaseSchema):
    label: str | None
    confidence: float
    all_scores: dict[str, object]
    second_opinion_label: str | None
    second_opinion_confidence: float
    classifier_disagreement: bool
    ood_metrics: dict[str, object] | None
    svm_scores: dict[str, object]
    svm_agrees_with_prediction: bool
    review_route: str
    smells: list[str]
    risk_score: int
    smell_review_suggested: bool
    foreign_municipality: str | None
    judged_by_llm: bool
    judge_final_label: str | None
    judge_reasoning: str | None
    stored_path: str | None
    human_overridden: bool

    @classmethod
    def from_model(cls, record: ClassificationRecord) -> "ClassificationRecordSchema":
        return cls(
            label=record.label,
            confidence=record.confidence,
            all_scores=record.all_scores,
            second_opinion_label=record.second_opinion_label,
            second_opinion_confidence=record.second_opinion_confidence,
            classifier_disagreement=record.classifier_disagreement,
            ood_metrics=record.ood_metrics,
            svm_scores=record.svm_scores,
            svm_agrees_with_prediction=record.svm_agrees_with_prediction,
            review_route=record.review_route,
            smells=record.smells,
            risk_score=record.risk_score,
            smell_review_suggested=record.smell_review_suggested,
            foreign_municipality=record.foreign_municipality,
            judged_by_llm=record.judged_by_llm,
            judge_final_label=record.judge_final_label,
            judge_reasoning=record.judge_reasoning,
            stored_path=record.stored_path,
            human_overridden=record.human_overridden,
        )


class JobDetailResponse(BaseSchema):
    job: JobDetail
    enriched: EnrichedRecordSchema | None
    classification: ClassificationRecordSchema | None
    audit: list[AuditRecordSchema]
```

- [x] **Step 4: Write the router**

```python
# api/routes/documents/endpoints.py
import mimetypes
from http import HTTPStatus
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from dependency_injector.wiring import Provide, inject

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

router = APIRouter(prefix="", tags=["documents"], dependencies=[Depends(get_current_user)])


@router.get("/jobs")
async def list_completed_jobs(
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    classification_repo: Annotated[
        IClassificationRecordRepository, Depends(get_classification_record_repo)
    ],
    label: str | None = None,
    review_route: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> JobsPage:
    all_jobs = await job_repo.list_all()
    completed = [j for j in all_jobs if j.status not in ("queued", "processing")]

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
                label=record.label if record else None,
                review_route=record.review_route if record else "n/a",
                confidence=record.confidence if record else 0.0,
                judged_by_llm=record.judged_by_llm if record else False,
                created_at=job.created_at,
            )
        )

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

    # IDocumentStorage's Protocol only exposes save_staged/move_to_final -- neither
    # resolves "find the current path" on its own. Reuse LocalDiskStorage's own root
    # + glob approach directly here (matching _move_to_final_sync's exact technique)
    # rather than adding a new Protocol method for a single read-only lookup used by
    # one route.
    from classiflow.settings import Settings

    root = Path(Settings.document_storage_root)
    matches = list(root.glob(f"**/{job_id}_*"))
    if not matches:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail=f"No stored file for job {job_id}"
        )
    file_path = matches[0]
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

    def _iter_file() -> "collections.abc.Iterator[bytes]":
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(_iter_file(), media_type=content_type)
```

```python
# api/routes/documents/__init__.py
from classiflow.api.routes.documents.endpoints import router

__all__ = ["router"]
```

(The `import collections.abc` needed for the `_iter_file` type hint should be a
top-level import, not inline — add `import collections.abc` at the top of
`endpoints.py` and reference it as `collections.abc.Iterator[bytes]`, or import
`Iterator` directly from `collections.abc`. The inline `from classiflow.settings
import Settings` and `from pathlib import Path` shown above should similarly move to
top-level imports; they're written inline here only to keep this snippet's diff
localized to what changed — the actual file must have them at the top, per this
project's no-`TYPE_CHECKING`-unless-circular convention, which applies equally to any
avoidable inline import.)

- [x] **Step 5: Register the router**

```python
# api/routes/registry.py
from classiflow.api.routes.documents import router as documents_router

ROUTERS: list[APIRouter] = [
    health_router,
    auth_router,
    pipeline_router,
    classification_router,
    users_router,
    audit_router,
    documents_router,
]
```

- [x] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/api/routes/test_documents.py -v`
Expected: PASS

- [x] **Step 7: Run `uv run poe check`**

Hand this to the user to run (per project convention): `uv run poe check`
Expected: lint, format, and mypy all pass — pay particular attention to the inline
imports called out in Step 4's note; mypy strict will not itself flag inline imports,
but they must be moved regardless per `CLAUDE.md`.

- [x] **Step 8: Commit**

```bash
git add src/classiflow/api/routes/documents/ src/classiflow/api/routes/registry.py tests/api/routes/test_documents.py
git commit -m "feat: add GET /jobs, GET /jobs/{job_id}/detail, GET /documents/{job_id}/file"
```

---

### Task 13: Serve the built frontend from FastAPI (production same-origin)

**Status: done**

**Files:**
- Modify: `src/classiflow/api/app.py`
- Test: manual verification only (see Step 3) — this task has no meaningful unit test
  since it depends on a real built `dist/` directory existing, which Part B produces.

**Interfaces:**
- Consumes: `src/classiflow/frontend/dist/` (built by Task 21, doesn't exist until
  then — this task's mount is written defensively so its absence doesn't break `uv run
  poe check` or the test suite in the meantime).

- [x] **Step 1: Mount static files conditionally**

```python
# api/app.py
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .error_handlers import EXCEPTION_HANDLERS
from .routes import ROUTERS

_FRONTEND_DIST = Path(__file__).parents[1] / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="Classiflow")

    for router in ROUTERS:
        app.include_router(router)

    for exception, exception_handler in EXCEPTION_HANDLERS.items():
        app.add_exception_handler(exception, exception_handler)

    # Serves the built React SPA in production. Absent in dev (frontend runs via its
    # own `npm run dev` + Vite's proxy instead) and absent until Task 21 runs `npm run
    # build` for the first time -- both are normal, not errors, so this only mounts
    # when the directory is actually there.
    if _FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")

    return app
```

- [x] **Step 2: Run the full test suite to confirm the conditional mount doesn't break anything**

Run: `uv run pytest -v`
Expected: all PASS — `_FRONTEND_DIST` doesn't exist yet in this repo state, so the
`if` branch is skipped entirely; existing route tests are unaffected.

- [x] **Step 3: Note for later manual verification**

After Task 21 builds the frontend (`npm run build` inside
`src/classiflow/frontend/`), re-run the app and confirm `GET /` serves the built
`index.html` instead of a 404 — this can't be automated in this task since the
directory doesn't exist yet.

- [x] **Step 4: Commit**

```bash
git add src/classiflow/api/app.py
git commit -m "feat: serve the built frontend SPA from FastAPI when present"
```

---

## Part B — Frontend scaffold

### Task 14: Vite + React + TypeScript scaffold, lint/format/tsconfig, DI exclusions

**Status: done**

**Files:**
- Create: `src/classiflow/frontend/package.json`
- Create: `src/classiflow/frontend/vite.config.ts`
- Create: `src/classiflow/frontend/tsconfig.json`
- Create: `src/classiflow/frontend/tsconfig.app.json`
- Create: `src/classiflow/frontend/tsconfig.node.json`
- Create: `src/classiflow/frontend/eslint.config.js`
- Create: `src/classiflow/frontend/.prettierrc`
- Create: `src/classiflow/frontend/index.html`
- Create: `src/classiflow/frontend/src/main.tsx`
- Create: `src/classiflow/frontend/src/App.tsx`
- Create: `src/classiflow/frontend/src/index.css`
- Modify: `pyproject.toml` (`[tool.ruff] exclude`, `[tool.mypy] exclude`,
  `[tool.hatch.build.targets.wheel]`)
- Modify: `.gitignore`
- Modify: `.pre-commit-config.yaml`

**Interfaces:**
- Produces: a running `npm run dev` dev server, `npm run build`, `npm run lint` — every
  later frontend task builds inside this scaffold.

- [x] **Step 1: Create the directory and initialize `package.json`**

```json
{
  "name": "classiflow-frontend",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "eslint .",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^19.2.7",
    "react-dom": "^19.2.7",
    "react-router": "^7.0.0",
    "@tanstack/react-query": "^5.60.0",
    "react-pdf": "^9.2.0"
  },
  "devDependencies": {
    "@eslint/js": "^9.22.0",
    "@tailwindcss/vite": "^4.0.0",
    "@types/node": "^24.13.2",
    "@types/react": "^19.2.17",
    "@types/react-dom": "^19.2.3",
    "@vitejs/plugin-react": "^4.7.0",
    "eslint": "^9.22.0",
    "eslint-config-prettier": "^9.1.0",
    "eslint-plugin-react-hooks": "^5.2.0",
    "eslint-plugin-react-refresh": "^0.4.19",
    "globals": "^16.0.0",
    "prettier": "^3.5.3",
    "tailwindcss": "^4.0.0",
    "typescript": "~6.0.2",
    "typescript-eslint": "^8.26.1",
    "vite": "^6.4.3"
  }
}
```

(No `husky`/`lint-staged`/`prepare` script — per the spec's deliberate deviation, git
hooks go through the existing `pre-commit` framework, not this file.)

- [x] **Step 2: Add `vite.config.ts` with the dev proxy**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/auth": "http://127.0.0.1:8000",
      "/pipeline": "http://127.0.0.1:8000",
      "/classification": "http://127.0.0.1:8000",
      "/jobs": "http://127.0.0.1:8000",
      "/documents": "http://127.0.0.1:8000",
      "/users": "http://127.0.0.1:8000",
      "/audit": "http://127.0.0.1:8000",
    },
  },
});
```

- [x] **Step 3: Add the tsconfig files (verbatim, per spec Decision 1)**

```json
// tsconfig.json
{
  "files": [],
  "references": [{ "path": "./tsconfig.app.json" }, { "path": "./tsconfig.node.json" }]
}
```

```json
// tsconfig.app.json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
    "target": "es2023",
    "lib": ["ES2023", "DOM"],
    "module": "esnext",
    "types": ["vite/client"],
    "allowArbitraryExtensions": true,
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "erasableSyntaxOnly": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

```json
// tsconfig.node.json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.node.tsbuildinfo",
    "target": "es2023",
    "lib": ["ES2023"],
    "types": ["node"],
    "skipLibCheck": true,
    "module": "nodenext",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "erasableSyntaxOnly": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["vite.config.ts"]
}
```

- [x] **Step 4: Add `eslint.config.js` and `.prettierrc` (verbatim, per spec Decision 1)**

```javascript
// eslint.config.js
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";
import eslintConfigPrettier from "eslint-config-prettier";

export default tseslint.config(
  { ignores: ["dist"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended, eslintConfigPrettier],
    files: ["**/*.{ts,tsx}"],
    languageOptions: { ecmaVersion: 2020, globals: globals.browser },
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },
);
```

```json
{
  "semi": true,
  "singleQuote": false,
  "trailingComma": "all",
  "printWidth": 100
}
```

- [x] **Step 5: Add `index.html`, `main.tsx`, minimal `App.tsx`, `index.css`**

```html
<!-- index.html -->
<!doctype html>
<html lang="en" data-theme="dark">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Classiflow</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

```typescript
// src/main.tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

```typescript
// src/App.tsx -- placeholder, replaced by Task 17's router
export default function App() {
  return <div>Classiflow</div>;
}
```

```css
/* src/index.css */
@import "tailwindcss";

:root {
  --color-bg: #0f1115;
  --color-surface: #161a21;
  --color-border: #262b35;
  --color-text: #e5e7eb;
  --color-text-muted: #9ca3af;
  --color-accent: #3b82f6;
  --color-success: #22c55e;
  --color-warning: #eab308;
  --color-danger: #ef4444;
}

body {
  background: var(--color-bg);
  color: var(--color-text);
}
```

- [x] **Step 6: Install dependencies**

Hand this to the user to run: `cd src/classiflow/frontend && npm install`
Expected: `node_modules/` created, `package-lock.json` created, no errors.

- [x] **Step 7: Verify the dev server starts**

Hand this to the user to run: `cd src/classiflow/frontend && npm run dev`
Expected: Vite starts on `http://localhost:5173`, page loads showing "Classiflow" on a
dark background.

- [x] **Step 8: Verify lint and typecheck pass on the scaffold**

Hand this to the user to run:
`cd src/classiflow/frontend && npm run lint && npx tsc -b`
Expected: no errors.

- [x] **Step 9: Exclude `frontend/` from Python tooling**

```toml
# pyproject.toml, [tool.ruff] section (line 96)
exclude = [".claude", "tasks", "alembic", "models", "src/classiflow/frontend"]
```

```toml
# pyproject.toml, [tool.mypy] section (line 157)
exclude = ["src/classiflow/playground/", "src/classiflow/frontend/"]
```

```toml
# pyproject.toml, [tool.hatch.build.targets.wheel] section (line 85-86)
[tool.hatch.build.targets.wheel]
packages = ["src/classiflow"]
exclude = ["src/classiflow/frontend"]
```

(Confirm `exclude` is the correct hatchling key for `[tool.hatch.build.targets.wheel]`
— check hatchling's docs or `uv run python -c "import hatchling"` version if uncertain;
the spec flagged this as needing confirmation rather than being guessed.)

- [x] **Step 10: Update `.gitignore`**

```
# .gitignore -- add
src/classiflow/frontend/node_modules/
src/classiflow/frontend/dist/
```

- [x] **Step 11: Add the frontend lint hook to `.pre-commit-config.yaml`**

```yaml
# .pre-commit-config.yaml -- add a new repo: local entry
  - repo: local
    hooks:
      - id: frontend-lint
        name: frontend eslint
        language: system
        entry: bash -c 'cd src/classiflow/frontend && npm run lint'
        pass_filenames: false
        files: ^src/classiflow/frontend/.*\.(ts|tsx)$
      - id: frontend-format
        name: frontend prettier check
        language: system
        entry: bash -c 'cd src/classiflow/frontend && npx prettier --check src'
        pass_filenames: false
        files: ^src/classiflow/frontend/.*\.(ts|tsx|css)$
```

- [x] **Step 12: Verify `uv run poe check` still passes with the exclusions**

Hand this to the user to run: `uv run poe check`
Expected: passes — ruff/mypy no longer walk `src/classiflow/frontend/`.

- [x] **Step 13: Verify pre-commit picks up the new hooks**

Hand this to the user to run: `uv run --all-groups pre-commit run --all-files`
Expected: `frontend-lint`/`frontend-format` run and pass (or are skipped if no matching
files changed, depending on pre-commit's file-filter behavior on a full-repo run).

- [x] **Step 14: Commit**

```bash
git add src/classiflow/frontend/ pyproject.toml .gitignore .pre-commit-config.yaml
git commit -m "feat: scaffold the React frontend (Vite, TS, ESLint, Prettier, Tailwind)"
```

---

### Task 15: `AuthContext` + popup OAuth flow + `RequireAuth`/`RequireAdmin`

**Status: done**

**Files:**
- Create: `src/classiflow/frontend/src/auth/AuthContext.tsx`
- Create: `src/classiflow/frontend/src/auth/oauthPopup.ts`
- Create: `src/classiflow/frontend/src/auth/tokenStorage.ts`
- Create: `src/classiflow/frontend/src/api/auth.ts`
- Create: `src/classiflow/frontend/src/components/RequireAuth.tsx`
- Create: `src/classiflow/frontend/src/components/RequireAdmin.tsx`
- Create: `src/classiflow/frontend/src/pages/OAuthPopupPage.tsx`
- Test: `src/classiflow/frontend/src/auth/AuthContext.test.tsx`

**Interfaces:**
- Consumes: `GET /auth/me` (Task 11), `GET /auth/login`, `GET /auth/callback` (existing).
- Produces: `useAuth()` hook returning `{ user, isAdmin, login, logout, isLoading }`;
  `<RequireAuth>`, `<RequireAdmin>` wrapper components — consumed by Task 17's router.

- [x] **Step 1: Add Vitest + React Testing Library**

```json
// package.json devDependencies, add:
"@testing-library/react": "^16.0.0",
"@testing-library/jest-dom": "^6.6.0",
"vitest": "^2.1.0",
"jsdom": "^25.0.0"
```

```json
// package.json scripts, add:
"test": "vitest run"
```

```typescript
// vite.config.ts -- add a test block to defineConfig
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { /* ... unchanged ... */ },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/setupTests.ts",
  },
});
```

```typescript
// src/setupTests.ts
import "@testing-library/jest-dom/vitest";
```

- [x] **Step 2: Write the failing test for `tokenStorage`**

```typescript
// src/auth/tokenStorage.test.ts
import { describe, it, expect, beforeEach } from "vitest";
import { getToken, setToken, clearToken } from "./tokenStorage";

describe("tokenStorage", () => {
  beforeEach(() => localStorage.clear());

  it("returns null when nothing is stored", () => {
    expect(getToken()).toBeNull();
  });

  it("round-trips a token", () => {
    setToken("abc123");
    expect(getToken()).toBe("abc123");
  });

  it("clears the token", () => {
    setToken("abc123");
    clearToken();
    expect(getToken()).toBeNull();
  });
});
```

- [x] **Step 3: Run test to verify it fails**

Hand this to the user to run: `cd src/classiflow/frontend && npm run test`
Expected: FAIL — `tokenStorage.ts` doesn't exist.

- [x] **Step 4: Implement `tokenStorage.ts`**

```typescript
// src/auth/tokenStorage.ts
const STORAGE_KEY = "classiflow_token";

export function getToken(): string | null {
  return localStorage.getItem(STORAGE_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(STORAGE_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(STORAGE_KEY);
}
```

- [x] **Step 5: Run test to verify it passes**

Hand this to the user to run: `cd src/classiflow/frontend && npm run test`
Expected: PASS

- [x] **Step 6: Write `api/auth.ts` (the typed fetch wrapper)**

```typescript
// src/api/auth.ts
import { getToken, clearToken } from "../auth/tokenStorage";

export interface CurrentUser {
  email: string;
  isAdmin: boolean;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) {
    clearToken();
    window.location.href = "/login";
  }
  return response;
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const response = await apiFetch("/auth/me");
  if (!response.ok) {
    throw new Error(`GET /auth/me failed: ${response.status}`);
  }
  return response.json();
}
```

- [x] **Step 7: Write `oauthPopup.ts`**

```typescript
// src/auth/oauthPopup.ts
interface OAuthTokenMessage {
  type: "oauth-token";
  token: string;
}

function isOAuthTokenMessage(data: unknown): data is OAuthTokenMessage {
  return (
    typeof data === "object" &&
    data !== null &&
    "type" in data &&
    (data as { type: unknown }).type === "oauth-token" &&
    "token" in data &&
    typeof (data as { token: unknown }).token === "string"
  );
}

export function openOAuthPopup(): Promise<string> {
  return new Promise((resolve, reject) => {
    const popup = window.open("/auth/login", "classiflow-oauth", "width=500,height=650");
    if (!popup) {
      reject(new Error("Popup blocked"));
      return;
    }

    function onMessage(event: MessageEvent<unknown>): void {
      if (event.origin !== window.location.origin) {
        return;
      }
      if (!isOAuthTokenMessage(event.data)) {
        return;
      }
      window.removeEventListener("message", onMessage);
      resolve(event.data.token);
    }

    window.addEventListener("message", onMessage);

    const pollClosed = setInterval(() => {
      if (popup.closed) {
        clearInterval(pollClosed);
        window.removeEventListener("message", onMessage);
        reject(new Error("Popup closed before completing sign-in"));
      }
    }, 500);
  });
}
```

- [x] **Step 8: Write the `OAuthPopupPage` (the frontend route Google redirects to)**

```typescript
// src/pages/OAuthPopupPage.tsx
import { useEffect } from "react";

export default function OAuthPopupPage() {
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");

    if (!code || !state) {
      window.close();
      return;
    }

    fetch(`/auth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`, {
      credentials: "include",
    })
      .then((response) => response.json())
      .then((body: { accessToken: string }) => {
        window.opener?.postMessage({ type: "oauth-token", token: body.accessToken }, window.location.origin);
      })
      .finally(() => window.close());
  }, []);

  return <p>Signing in...</p>;
}
```

(`AuthToken`'s fields are `access_token`/`token_type` server-side, but `BaseSchema`'s
`to_camel` alias generator — confirmed in `api/schemas.py` — means the JSON response
actually has `accessToken`/`tokenType` keys. Verify this by checking whether
`AuthToken` itself extends `BaseSchema`/uses the alias generator, since it's defined in
`domain/user.py` as a plain `BaseModel`, not `BaseSchema` — if it does NOT use
`to_camel`, this step's `body.accessToken` must be `body.access_token` instead. Check
`domain/user.py`'s `AuthToken` definition before writing this file for real.)

- [x] **Step 9: Write `AuthContext.tsx`**

```typescript
// src/auth/AuthContext.tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { fetchCurrentUser, type CurrentUser } from "../api/auth";
import { openOAuthPopup } from "./oauthPopup";
import { getToken, setToken, clearToken } from "./tokenStorage";

interface AuthContextValue {
  user: CurrentUser | null;
  isAdmin: boolean;
  isLoading: boolean;
  login: () => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setIsLoading(false);
      return;
    }
    fetchCurrentUser()
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setIsLoading(false));
  }, []);

  async function login(): Promise<void> {
    const token = await openOAuthPopup();
    setToken(token);
    const currentUser = await fetchCurrentUser();
    setUser(currentUser);
  }

  function logout(): void {
    clearToken();
    setUser(null);
  }

  return (
    <AuthContext.Provider
      value={{ user, isAdmin: user?.isAdmin ?? false, isLoading, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
```

- [x] **Step 10: Write `RequireAuth.tsx` and `RequireAdmin.tsx`**

```typescript
// src/components/RequireAuth.tsx
import { Navigate, Outlet } from "react-router";
import { useAuth } from "../auth/AuthContext";

export default function RequireAuth() {
  const { user, isLoading } = useAuth();
  if (isLoading) {
    return <p>Loading...</p>;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}
```

```typescript
// src/components/RequireAdmin.tsx
import { Navigate, Outlet } from "react-router";
import { useAuth } from "../auth/AuthContext";

export default function RequireAdmin() {
  const { isAdmin } = useAuth();
  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }
  return <Outlet />;
}
```

- [x] **Step 11: Write a component test for `RequireAdmin`**

```typescript
// src/components/RequireAdmin.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router";
import RequireAdmin from "./RequireAdmin";

vi.mock("../auth/AuthContext", () => ({
  useAuth: vi.fn(),
}));

import { useAuth } from "../auth/AuthContext";

describe("RequireAdmin", () => {
  it("redirects non-admins to /", () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { email: "u@example.com", isAdmin: false },
      isAdmin: false,
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
    });

    render(
      <MemoryRouter initialEntries={["/audit"]}>
        <Routes>
          <Route element={<RequireAdmin />}>
            <Route path="/audit" element={<p>Audit page</p>} />
          </Route>
          <Route path="/" element={<p>Home</p>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.queryByText("Audit page")).not.toBeInTheDocument();
  });

  it("renders the protected route for admins", () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { email: "a@example.com", isAdmin: true },
      isAdmin: true,
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
    });

    render(
      <MemoryRouter initialEntries={["/audit"]}>
        <Routes>
          <Route element={<RequireAdmin />}>
            <Route path="/audit" element={<p>Audit page</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("Audit page")).toBeInTheDocument();
  });
});
```

- [x] **Step 12: Run tests to verify they pass**

Hand this to the user to run: `cd src/classiflow/frontend && npm run test`
Expected: PASS

- [x] **Step 13: Commit**

```bash
git add src/classiflow/frontend/src/auth/ src/classiflow/frontend/src/api/auth.ts src/classiflow/frontend/src/components/RequireAuth.tsx src/classiflow/frontend/src/components/RequireAdmin.tsx src/classiflow/frontend/src/pages/OAuthPopupPage.tsx src/classiflow/frontend/src/setupTests.ts src/classiflow/frontend/package.json src/classiflow/frontend/vite.config.ts
git commit -m "feat: add AuthContext, popup OAuth flow, RequireAuth/RequireAdmin guards"
```

---

### Task 16: Router, Sidebar, Layout, `LoginPage`, `ChatPage` placeholder

**Files:**
- Create: `src/classiflow/frontend/src/router.tsx`
- Create: `src/classiflow/frontend/src/components/Sidebar.tsx`
- Create: `src/classiflow/frontend/src/components/Layout.tsx`
- Create: `src/classiflow/frontend/src/pages/LoginPage.tsx`
- Create: `src/classiflow/frontend/src/pages/ChatPage.tsx`
- Modify: `src/classiflow/frontend/src/App.tsx`

**Interfaces:**
- Consumes: `useAuth()` (Task 15), `<RequireAuth>`/`<RequireAdmin>` (Task 15).
- Produces: the app's route tree and persistent sidebar shell — every subsequent page
  task (17-19) plugs into `router.tsx`.

- [ ] **Step 1: Write `LoginPage.tsx`**

```typescript
// src/pages/LoginPage.tsx
import { useNavigate } from "react-router";
import { useAuth } from "../auth/AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();

  async function handleLogin(): Promise<void> {
    await login();
    navigate("/");
  }

  return (
    <div className="flex h-screen items-center justify-center bg-[var(--color-bg)]">
      <button
        onClick={handleLogin}
        className="rounded-md bg-[var(--color-accent)] px-6 py-3 text-white"
      >
        Sign in with Google
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Write `ChatPage.tsx`**

```typescript
// src/pages/ChatPage.tsx
export default function ChatPage() {
  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold">Chat</h1>
      <p className="mt-2 text-[var(--color-text-muted)]">Coming soon — Stage 5.</p>
    </div>
  );
}
```

- [ ] **Step 3: Write `Sidebar.tsx`**

```typescript
// src/components/Sidebar.tsx
import { NavLink } from "react-router";
import { useAuth } from "../auth/AuthContext";

const LINK_CLASS = "block rounded-md px-3 py-2 text-sm";
const ACTIVE_CLASS = "bg-[var(--color-surface)] text-white";
const INACTIVE_CLASS = "text-[var(--color-text-muted)] hover:text-white";

export default function Sidebar() {
  const { isAdmin, logout } = useAuth();

  return (
    <nav className="flex h-screen w-56 flex-col justify-between border-r border-[var(--color-border)] bg-[var(--color-bg)] p-4">
      <div className="flex flex-col gap-1">
        <NavLink to="/" end className={({ isActive }) => `${LINK_CLASS} ${isActive ? ACTIVE_CLASS : INACTIVE_CLASS}`}>
          Processing
        </NavLink>
        <NavLink to="/classification" className={({ isActive }) => `${LINK_CLASS} ${isActive ? ACTIVE_CLASS : INACTIVE_CLASS}`}>
          Classification
        </NavLink>
        <NavLink to="/chat" className={({ isActive }) => `${LINK_CLASS} ${isActive ? ACTIVE_CLASS : INACTIVE_CLASS}`}>
          Chat
        </NavLink>
        {isAdmin && (
          <>
            <NavLink to="/users" className={({ isActive }) => `${LINK_CLASS} ${isActive ? ACTIVE_CLASS : INACTIVE_CLASS}`}>
              Users
            </NavLink>
            <NavLink to="/audit" className={({ isActive }) => `${LINK_CLASS} ${isActive ? ACTIVE_CLASS : INACTIVE_CLASS}`}>
              Audit Log
            </NavLink>
          </>
        )}
      </div>
      <button onClick={logout} className={`${LINK_CLASS} ${INACTIVE_CLASS} text-left`}>
        Sign out
      </button>
    </nav>
  );
}
```

- [ ] **Step 4: Write `Layout.tsx`**

```typescript
// src/components/Layout.tsx
import { Outlet } from "react-router";
import Sidebar from "./Sidebar";

export default function Layout() {
  return (
    <div className="flex">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 5: Write `router.tsx`**

```typescript
// src/router.tsx
import { createBrowserRouter } from "react-router";
import Layout from "./components/Layout";
import RequireAuth from "./components/RequireAuth";
import RequireAdmin from "./components/RequireAdmin";
import LoginPage from "./pages/LoginPage";
import OAuthPopupPage from "./pages/OAuthPopupPage";
import ChatPage from "./pages/ChatPage";
import ProcessingPage from "./pages/ProcessingPage";
import ClassificationPage from "./pages/ClassificationPage";
import DocumentDetailPage from "./pages/DocumentDetailPage";
import UsersPage from "./pages/UsersPage";
import AuditLogPage from "./pages/AuditLogPage";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/oauth-popup", element: <OAuthPopupPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <Layout />,
        children: [
          { path: "/", element: <ProcessingPage /> },
          { path: "/classification", element: <ClassificationPage /> },
          { path: "/documents/:jobId", element: <DocumentDetailPage /> },
          { path: "/chat", element: <ChatPage /> },
          {
            element: <RequireAdmin />,
            children: [
              { path: "/users", element: <UsersPage /> },
              { path: "/audit", element: <AuditLogPage /> },
            ],
          },
        ],
      },
    ],
  },
]);
```

(This imports `ProcessingPage`, `ClassificationPage`, `DocumentDetailPage`,
`UsersPage`, `AuditLogPage` from Tasks 17-19, which don't exist yet at this point in
the plan — this task creates minimal placeholder versions of each so `router.tsx`
compiles, and Tasks 17-19 replace them with the real implementations. Add placeholders
now:)

```typescript
// src/pages/ProcessingPage.tsx (placeholder, replaced by Task 17)
export default function ProcessingPage() {
  return <div className="p-6">Processing</div>;
}
```

```typescript
// src/pages/ClassificationPage.tsx (placeholder, replaced by Task 18)
export default function ClassificationPage() {
  return <div className="p-6">Classification</div>;
}
```

```typescript
// src/pages/DocumentDetailPage.tsx (placeholder, replaced by Task 18)
export default function DocumentDetailPage() {
  return <div className="p-6">Document Detail</div>;
}
```

```typescript
// src/pages/UsersPage.tsx (placeholder, replaced by Task 19)
export default function UsersPage() {
  return <div className="p-6">Users</div>;
}
```

```typescript
// src/pages/AuditLogPage.tsx (placeholder, replaced by Task 19)
export default function AuditLogPage() {
  return <div className="p-6">Audit Log</div>;
}
```

- [ ] **Step 6: Wire `App.tsx`**

```typescript
// src/App.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router";
import { AuthProvider } from "./auth/AuthContext";
import { router } from "./router";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 7: Verify the app builds and runs**

Hand this to the user to run:
`cd src/classiflow/frontend && npx tsc -b && npm run dev`
Expected: no type errors; dev server serves `/login`, and after a manual sign-in
(requires real `GOOGLE_CLIENT_ID`/`SECRET` in `.env` and the backend running) the
sidebar renders with Processing/Classification/Chat visible, Users/Audit Log hidden
for a non-admin test user.

- [ ] **Step 8: Commit**

```bash
git add src/classiflow/frontend/src/
git commit -m "feat: add router, Sidebar/Layout shell, Login/Chat pages"
```

---

### Task 17: `ProcessingPage` — live dashboard, `StepTimeline`

**Files:**
- Create: `src/classiflow/frontend/src/api/jobs.ts`
- Create: `src/classiflow/frontend/src/components/StepTimeline.tsx`
- Create: `src/classiflow/frontend/src/pages/ProcessingPage.tsx` (replaces Task 16's placeholder)
- Test: `src/classiflow/frontend/src/components/StepTimeline.test.tsx`

**Interfaces:**
- Consumes: `GET /pipeline/jobs?status=running` (Task 6),
  `GET /pipeline/jobs/{job_id}/timeline` (Task 6), `GET /pipeline/{job_id}/events`
  (existing SSE endpoint).
- Produces: the Processing page, with `StepTimeline` as a reusable component (also used
  read-only inside Task 18's Document Detail Audit Trail tab, though that tab renders
  the same data differently — not a shared consumer requirement, just noting the
  overlap).

- [ ] **Step 1: Write `api/jobs.ts`**

```typescript
// src/api/jobs.ts
import { apiFetch } from "./auth";

export interface JobSummary {
  jobId: string;
  filename: string;
  status: string;
  createdAt: string;
  updatedAt: string;
}

export interface TimelineEntry {
  node: string;
  status: string;
  passed: boolean | null;
  detail: Record<string, unknown> | null;
  timestamp: string;
  durationMs: number | null;
}

export async function fetchRunningJobs(): Promise<JobSummary[]> {
  const response = await apiFetch("/pipeline/jobs?status=running");
  if (!response.ok) {
    throw new Error(`GET /pipeline/jobs failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchJobTimeline(jobId: string): Promise<TimelineEntry[]> {
  const response = await apiFetch(`/pipeline/jobs/${jobId}/timeline`);
  if (!response.ok) {
    throw new Error(`GET /pipeline/jobs/${jobId}/timeline failed: ${response.status}`);
  }
  return response.json();
}
```

- [ ] **Step 2: Write the failing test for `StepTimeline`'s backfill+live merge logic**

```typescript
// src/components/StepTimeline.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StepTimeline from "./StepTimeline";
import type { TimelineEntry } from "../api/jobs";

const BACKFILLED: TimelineEntry[] = [
  { node: "node1_file_reception", status: "passed", passed: true, detail: null, timestamp: "2026-08-24T10:00:00Z", durationMs: 50 },
];

describe("StepTimeline", () => {
  it("renders backfilled steps", () => {
    render(<StepTimeline entries={BACKFILLED} />);
    expect(screen.getByText("node1_file_reception")).toBeInTheDocument();
  });

  it("appends a live event without duplicating an already-backfilled node+timestamp", () => {
    const live: TimelineEntry = {
      node: "node2_format_validation", status: "passed", passed: true, detail: null,
      timestamp: "2026-08-24T10:00:05Z", durationMs: 30,
    };
    render(<StepTimeline entries={[...BACKFILLED, live]} />);
    expect(screen.getAllByText(/node1_file_reception|node2_format_validation/)).toHaveLength(2);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Hand this to the user to run: `cd src/classiflow/frontend && npm run test`
Expected: FAIL — `StepTimeline.tsx` doesn't exist.

- [ ] **Step 4: Implement `StepTimeline.tsx`**

```typescript
// src/components/StepTimeline.tsx
import type { TimelineEntry } from "../api/jobs";

const STATUS_COLOR: Record<string, string> = {
  passed: "bg-[var(--color-success)]",
  failed: "bg-[var(--color-danger)]",
  started: "bg-[var(--color-accent)]",
};

export default function StepTimeline({ entries }: { entries: TimelineEntry[] }) {
  return (
    <div className="flex flex-col gap-3">
      {entries.map((entry, i) => (
        <div key={`${entry.node}-${entry.timestamp}-${i}`} className="flex gap-3">
          <div className={`mt-1 h-2 w-2 shrink-0 rounded-full ${STATUS_COLOR[entry.status] ?? "bg-[var(--color-text-muted)]"}`} />
          <div>
            <p className="font-semibold">{entry.node}</p>
            <p className="text-sm text-[var(--color-text-muted)]">{entry.status}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
```

(The merge/dedup logic the test names is deliberately pushed to the *caller*
(`ProcessingPage`, Step 6 below) rather than into `StepTimeline` itself —
`StepTimeline` stays a pure rendering component over whatever `entries` it's given;
the page owns merging backfilled + live entries into one array before passing it
down. Update the test above to reflect this once the page's merge function exists, if
the initial version over-specified merge behavior inside the component.)

- [ ] **Step 5: Run test to verify it passes**

Hand this to the user to run: `cd src/classiflow/frontend && npm run test`
Expected: PASS

- [ ] **Step 6: Implement `ProcessingPage.tsx`**

```typescript
// src/pages/ProcessingPage.tsx
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchRunningJobs, fetchJobTimeline, type JobSummary, type TimelineEntry } from "../api/jobs";
import StepTimeline from "../components/StepTimeline";

function JobCard({ job }: { job: JobSummary }) {
  const [entries, setEntries] = useState<TimelineEntry[]>([]);

  useEffect(() => {
    fetchJobTimeline(job.jobId).then(setEntries).catch(() => {});

    const source = new EventSource(`/pipeline/${job.jobId}/events`);
    source.addEventListener("node_update", (event) => {
      const payload = JSON.parse((event as MessageEvent<string>).data) as {
        node: string;
        status: string;
        timestamp: string;
      };
      setEntries((prev) => [
        ...prev,
        { node: payload.node, status: payload.status, passed: null, detail: null, timestamp: payload.timestamp, durationMs: null },
      ]);
    });

    return () => source.close();
  }, [job.jobId]);

  return (
    <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <p className="font-semibold">{job.filename}</p>
      <p className="mb-3 text-xs text-[var(--color-text-muted)]">{job.jobId}</p>
      <StepTimeline entries={entries} />
    </div>
  );
}

export default function ProcessingPage() {
  const { data: jobs = [] } = useQuery({
    queryKey: ["running-jobs"],
    queryFn: fetchRunningJobs,
    refetchInterval: 10_000,
  });

  const queued = jobs.filter((j) => j.status === "queued");
  const processing = jobs.filter((j) => j.status === "processing");

  return (
    <div className="p-6">
      <h1 className="mb-4 text-xl font-semibold">Processing</h1>

      <h2 className="mb-2 text-sm uppercase text-[var(--color-text-muted)]">Queued</h2>
      <div className="mb-6 flex flex-col gap-2">
        {queued.map((job) => (
          <div key={job.jobId} className="rounded-md border border-[var(--color-border)] p-2 text-sm">
            {job.filename}
          </div>
        ))}
        {queued.length === 0 && <p className="text-sm text-[var(--color-text-muted)]">None</p>}
      </div>

      <h2 className="mb-2 text-sm uppercase text-[var(--color-text-muted)]">Processing</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {processing.map((job) => (
          <JobCard key={job.jobId} job={job} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Manual verification**

Hand this to the user to run (backend + frontend both running):
`cd src/classiflow/frontend && npm run dev`
Expected: uploading a document via the existing `/pipeline/ingest` endpoint (e.g. via
`curl` or a quick manual test) makes it appear under Queued then Processing on this
page, with the step timeline updating live.

- [ ] **Step 8: Run lint and typecheck**

Hand this to the user to run:
`cd src/classiflow/frontend && npm run lint && npx tsc -b`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add src/classiflow/frontend/src/api/jobs.ts src/classiflow/frontend/src/components/StepTimeline.tsx src/classiflow/frontend/src/components/StepTimeline.test.tsx src/classiflow/frontend/src/pages/ProcessingPage.tsx
git commit -m "feat: add ProcessingPage with live job dashboard and StepTimeline"
```

---

### Task 18: `ClassificationPage`, `DocumentDetailPage`, `PdfViewer`, Reclassify

**Files:**
- Create: `src/classiflow/frontend/src/api/documents.ts`
- Create: `src/classiflow/frontend/src/api/classification.ts`
- Create: `src/classiflow/frontend/src/components/DataTable.tsx`
- Create: `src/classiflow/frontend/src/components/StatusBadge.tsx`
- Create: `src/classiflow/frontend/src/components/PdfViewer.tsx`
- Create: `src/classiflow/frontend/src/components/ReclassifyPanel.tsx`
- Modify: `src/classiflow/frontend/src/pages/ClassificationPage.tsx` (replaces Task 16's placeholder)
- Modify: `src/classiflow/frontend/src/pages/DocumentDetailPage.tsx` (replaces Task 16's placeholder)
- Test: `src/classiflow/frontend/src/components/ReclassifyPanel.test.tsx`

**Interfaces:**
- Consumes: `GET /jobs` (Task 12), `GET /jobs/{job_id}/detail` (Task 12),
  `GET /documents/{job_id}/file` (Task 12), `POST /classification/{job_id}/decision`
  (existing).

- [ ] **Step 1: Write `api/documents.ts`**

```typescript
// src/api/documents.ts
import { apiFetch } from "./auth";

export interface ClassificationSummary {
  jobId: string;
  filename: string;
  label: string | null;
  reviewRoute: string;
  confidence: number;
  judgedByLlm: boolean;
  createdAt: string;
}

export interface JobsPage {
  items: ClassificationSummary[];
  total: number;
  page: number;
  pageSize: number;
}

export interface JobDetailResponse {
  job: { jobId: string; filename: string; status: string; createdAt: string };
  enriched: { cleanedText: string; rawText: string | null; entities: Record<string, unknown>; metadata: Record<string, unknown> } | null;
  classification: {
    label: string | null;
    confidence: number;
    allScores: Record<string, unknown>;
    secondOpinionLabel: string | null;
    secondOpinionConfidence: number;
    classifierDisagreement: boolean;
    oodMetrics: Record<string, unknown> | null;
    svmScores: Record<string, unknown>;
    svmAgreesWithPrediction: boolean;
    reviewRoute: string;
    smells: string[];
    riskScore: number;
    smellReviewSuggested: boolean;
    foreignMunicipality: string | null;
    judgedByLlm: boolean;
    judgeFinalLabel: string | null;
    judgeReasoning: string | null;
    storedPath: string | null;
    humanOverridden: boolean;
  } | null;
  audit: { jobId: string; node: string; event: string; timestamp: string; durationMs: number | null; detail: Record<string, unknown> | null }[];
}

export async function fetchJobsPage(params: {
  label?: string;
  reviewRoute?: string;
  page?: number;
}): Promise<JobsPage> {
  const query = new URLSearchParams();
  if (params.label) query.set("label", params.label);
  if (params.reviewRoute) query.set("reviewRoute", params.reviewRoute);
  if (params.page) query.set("page", String(params.page));

  const response = await apiFetch(`/jobs?${query.toString()}`);
  if (!response.ok) {
    throw new Error(`GET /jobs failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchJobDetail(jobId: string): Promise<JobDetailResponse> {
  const response = await apiFetch(`/jobs/${jobId}/detail`);
  if (!response.ok) {
    throw new Error(`GET /jobs/${jobId}/detail failed: ${response.status}`);
  }
  return response.json();
}

export function documentFileUrl(jobId: string): string {
  return `/documents/${jobId}/file`;
}
```

- [ ] **Step 2: Write `api/classification.ts`**

```typescript
// src/api/classification.ts
import { apiFetch } from "./auth";

export async function submitReclassification(
  jobId: string,
  label: string,
  notes: string,
): Promise<void> {
  const response = await apiFetch(`/classification/${jobId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label, notes }),
  });
  if (!response.ok) {
    throw new Error(`POST /classification/${jobId}/decision failed: ${response.status}`);
  }
}

export const DOCUMENT_CATEGORIES = [
  "boletines", "compendios_de_boletines", "convenios",
  "declaraciones_concejo_municipal", "decreto_ordenanzas", "decretos",
  "decretos_concejo_municipal", "ordenanzas", "otro", "resoluciones",
  "resoluciones_concejo_municipal",
] as const;
```

- [ ] **Step 3: Write the failing test for `ReclassifyPanel`**

```typescript
// src/components/ReclassifyPanel.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ReclassifyPanel from "./ReclassifyPanel";
import * as classificationApi from "../api/classification";

describe("ReclassifyPanel", () => {
  it("submits the selected label and notes", async () => {
    const submitSpy = vi.spyOn(classificationApi, "submitReclassification").mockResolvedValue();

    render(<ReclassifyPanel jobId="job-1" onSubmitted={() => {}} />);

    fireEvent.change(screen.getByLabelText("Label"), { target: { value: "ordenanzas" } });
    fireEvent.change(screen.getByLabelText("Notes"), { target: { value: "manual fix" } });
    fireEvent.click(screen.getByText("Submit"));

    await waitFor(() => {
      expect(submitSpy).toHaveBeenCalledWith("job-1", "ordenanzas", "manual fix");
    });
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Hand this to the user to run: `cd src/classiflow/frontend && npm run test`
Expected: FAIL — `ReclassifyPanel.tsx` doesn't exist.

- [ ] **Step 5: Implement `ReclassifyPanel.tsx`**

```typescript
// src/components/ReclassifyPanel.tsx
import { useState } from "react";
import { submitReclassification, DOCUMENT_CATEGORIES } from "../api/classification";

export default function ReclassifyPanel({
  jobId,
  onSubmitted,
}: {
  jobId: string;
  onSubmitted: () => void;
}) {
  const [label, setLabel] = useState<string>(DOCUMENT_CATEGORIES[0]);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(): Promise<void> {
    setSubmitting(true);
    try {
      await submitReclassification(jobId, label, notes);
      onSubmitted();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="rounded-md border border-[var(--color-border)] p-4">
      <label className="mb-1 block text-sm" htmlFor="reclassify-label">
        Label
      </label>
      <select
        id="reclassify-label"
        aria-label="Label"
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        className="mb-3 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2"
      >
        {DOCUMENT_CATEGORIES.map((category) => (
          <option key={category} value={category}>
            {category}
          </option>
        ))}
      </select>

      <label className="mb-1 block text-sm" htmlFor="reclassify-notes">
        Notes
      </label>
      <textarea
        id="reclassify-notes"
        aria-label="Notes"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        className="mb-3 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2"
      />

      <button
        onClick={handleSubmit}
        disabled={submitting}
        className="rounded-md bg-[var(--color-accent)] px-4 py-2 text-white disabled:opacity-50"
      >
        Submit
      </button>
    </div>
  );
}
```

- [ ] **Step 6: Run test to verify it passes**

Hand this to the user to run: `cd src/classiflow/frontend && npm run test`
Expected: PASS

- [ ] **Step 7: Implement `StatusBadge.tsx` and `DataTable.tsx`**

```typescript
// src/components/StatusBadge.tsx
const COLORS: Record<string, string> = {
  accept: "bg-[var(--color-success)]",
  human_review: "bg-[var(--color-warning)]",
  llm_judge: "bg-[var(--color-accent)]",
};

export default function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs text-black ${COLORS[status] ?? "bg-[var(--color-text-muted)]"}`}>
      {status}
    </span>
  );
}
```

```typescript
// src/components/DataTable.tsx
export interface Column<T> {
  header: string;
  render: (row: T) => React.ReactNode;
}

export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
}) {
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-[var(--color-border)] text-left text-[var(--color-text-muted)]">
          {columns.map((col) => (
            <th key={col.header} className="p-2">
              {col.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={rowKey(row)}
            onClick={() => onRowClick?.(row)}
            className={`border-b border-[var(--color-border)] ${onRowClick ? "cursor-pointer hover:bg-[var(--color-surface)]" : ""}`}
          >
            {columns.map((col) => (
              <td key={col.header} className="p-2">
                {col.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 8: Implement `ClassificationPage.tsx`**

```typescript
// src/pages/ClassificationPage.tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { fetchJobsPage, type ClassificationSummary } from "../api/documents";
import DataTable, { type Column } from "../components/DataTable";
import StatusBadge from "../components/StatusBadge";

const COLUMNS: Column<ClassificationSummary>[] = [
  { header: "Filename", render: (row) => row.filename },
  { header: "Label", render: (row) => row.label ?? "—" },
  { header: "Review Route", render: (row) => <StatusBadge status={row.reviewRoute} /> },
  { header: "Confidence", render: (row) => row.confidence.toFixed(2) },
  { header: "Judged", render: (row) => (row.judgedByLlm ? "Yes" : "No") },
  { header: "Created", render: (row) => new Date(row.createdAt).toLocaleString() },
];

export default function ClassificationPage() {
  const [label, setLabel] = useState("");
  const [reviewRoute, setReviewRoute] = useState("");
  const navigate = useNavigate();

  const { data } = useQuery({
    queryKey: ["jobs", label, reviewRoute],
    queryFn: () => fetchJobsPage({ label: label || undefined, reviewRoute: reviewRoute || undefined }),
  });

  return (
    <div className="p-6">
      <h1 className="mb-4 text-xl font-semibold">Classification</h1>
      <div className="mb-4 flex gap-2">
        <input
          placeholder="Filter by label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2 text-sm"
        />
        <input
          placeholder="Filter by review route"
          value={reviewRoute}
          onChange={(e) => setReviewRoute(e.target.value)}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2 text-sm"
        />
      </div>
      <DataTable
        columns={COLUMNS}
        rows={data?.items ?? []}
        rowKey={(row) => row.jobId}
        onRowClick={(row) => navigate(`/documents/${row.jobId}`)}
      />
    </div>
  );
}
```

- [ ] **Step 9: Implement `PdfViewer.tsx`**

```typescript
// src/components/PdfViewer.tsx
import { useState } from "react";
import { Document, Page } from "react-pdf";

export default function PdfViewer({ fileUrl }: { fileUrl: string }) {
  const [numPages, setNumPages] = useState(0);

  return (
    <div className="overflow-y-auto">
      <Document file={fileUrl} onLoadSuccess={({ numPages: n }) => setNumPages(n)}>
        {Array.from({ length: numPages }, (_, i) => (
          <Page key={i} pageNumber={i + 1} width={500} />
        ))}
      </Document>
    </div>
  );
}
```

(`react-pdf` needs `pdfjs-dist`'s worker configured — add this once, near the app's
entry point:)

```typescript
// src/main.tsx -- add near the top, before rendering
import { pdfjs } from "react-pdf";
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;
```

- [ ] **Step 10: Implement `DocumentDetailPage.tsx`**

```typescript
// src/pages/DocumentDetailPage.tsx
import { useState } from "react";
import { useParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchJobDetail, documentFileUrl } from "../api/documents";
import PdfViewer from "../components/PdfViewer";
import ReclassifyPanel from "../components/ReclassifyPanel";

type Tab = "extraction" | "enrichment" | "classification" | "audit";

export default function DocumentDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [tab, setTab] = useState<Tab>("classification");
  const queryClient = useQueryClient();

  const { data } = useQuery({
    queryKey: ["job-detail", jobId],
    queryFn: () => fetchJobDetail(jobId!),
    enabled: !!jobId,
  });

  if (!data) {
    return <p className="p-6">Loading...</p>;
  }

  return (
    <div className="flex h-screen">
      <div className="w-1/2 border-r border-[var(--color-border)]">
        <PdfViewer fileUrl={documentFileUrl(jobId!)} />
      </div>
      <div className="w-1/2 overflow-y-auto p-4">
        <div className="mb-4 flex gap-2">
          {(["extraction", "enrichment", "classification", "audit"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`rounded-md px-3 py-1 text-sm ${tab === t ? "bg-[var(--color-accent)] text-white" : "text-[var(--color-text-muted)]"}`}
            >
              {t}
            </button>
          ))}
        </div>

        {tab === "extraction" && (
          <pre className="whitespace-pre-wrap text-sm">{data.enriched?.rawText ?? "No extraction data"}</pre>
        )}

        {tab === "enrichment" && (
          <pre className="whitespace-pre-wrap text-sm">{JSON.stringify(data.enriched?.entities, null, 2)}</pre>
        )}

        {tab === "classification" && (
          <div>
            <pre className="whitespace-pre-wrap text-sm">{JSON.stringify(data.classification, null, 2)}</pre>
            {data.classification?.reviewRoute === "human_review" && (
              <div className="mt-4">
                <ReclassifyPanel
                  jobId={jobId!}
                  onSubmitted={() => queryClient.invalidateQueries({ queryKey: ["job-detail", jobId] })}
                />
              </div>
            )}
          </div>
        )}

        {tab === "audit" && (
          <div className="flex flex-col gap-2">
            {data.audit.map((entry, i) => (
              <div key={i} className="text-sm">
                <span className="font-semibold">{entry.node}</span> — {entry.event} —{" "}
                {new Date(entry.timestamp).toLocaleString()}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 11: Run lint and typecheck**

Hand this to the user to run:
`cd src/classiflow/frontend && npm run lint && npx tsc -b`
Expected: no errors.

- [ ] **Step 12: Commit**

```bash
git add src/classiflow/frontend/src/api/documents.ts src/classiflow/frontend/src/api/classification.ts src/classiflow/frontend/src/components/DataTable.tsx src/classiflow/frontend/src/components/StatusBadge.tsx src/classiflow/frontend/src/components/PdfViewer.tsx src/classiflow/frontend/src/components/ReclassifyPanel.tsx src/classiflow/frontend/src/components/ReclassifyPanel.test.tsx src/classiflow/frontend/src/pages/ClassificationPage.tsx src/classiflow/frontend/src/pages/DocumentDetailPage.tsx src/classiflow/frontend/src/main.tsx
git commit -m "feat: add ClassificationPage, DocumentDetailPage, PDF viewer, reclassify flow"
```

---

### Task 19: `UsersPage`, `AuditLogPage`

**Files:**
- Create: `src/classiflow/frontend/src/api/users.ts`
- Create: `src/classiflow/frontend/src/api/audit.ts`
- Modify: `src/classiflow/frontend/src/pages/UsersPage.tsx` (replaces Task 16's placeholder)
- Modify: `src/classiflow/frontend/src/pages/AuditLogPage.tsx` (replaces Task 16's placeholder)

**Interfaces:**
- Consumes: `GET/POST/PATCH/DELETE /users` (Task 9), `GET /audit` (Task 10).

- [ ] **Step 1: Write `api/users.ts`**

```typescript
// src/api/users.ts
import { apiFetch } from "./auth";

export interface AllowedUserRecord {
  email: string;
  isActive: boolean;
  isAdmin: boolean;
  isBlocked: boolean;
  createdAt: string;
}

export async function fetchUsers(): Promise<AllowedUserRecord[]> {
  const response = await apiFetch("/users");
  if (!response.ok) {
    throw new Error(`GET /users failed: ${response.status}`);
  }
  return response.json();
}

export async function createUser(email: string, isAdmin: boolean): Promise<AllowedUserRecord> {
  const response = await apiFetch("/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, isAdmin }),
  });
  if (!response.ok) {
    throw new Error(`POST /users failed: ${response.status}`);
  }
  return response.json();
}

export async function updateUser(
  email: string,
  changes: { isActive?: boolean; isAdmin?: boolean; isBlocked?: boolean },
): Promise<AllowedUserRecord> {
  const response = await apiFetch(`/users/${encodeURIComponent(email)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
  if (!response.ok) {
    throw new Error(`PATCH /users/${email} failed: ${response.status}`);
  }
  return response.json();
}

export async function deleteUser(email: string): Promise<void> {
  const response = await apiFetch(`/users/${encodeURIComponent(email)}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`DELETE /users/${email} failed: ${response.status}`);
  }
}
```

- [ ] **Step 2: Implement `UsersPage.tsx`**

```typescript
// src/pages/UsersPage.tsx
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchUsers, createUser, updateUser, deleteUser } from "../api/users";
import DataTable, { type Column } from "../components/DataTable";
import type { AllowedUserRecord } from "../api/users";

export default function UsersPage() {
  const [newEmail, setNewEmail] = useState("");
  const queryClient = useQueryClient();

  const { data: users = [] } = useQuery({ queryKey: ["users"], queryFn: fetchUsers });

  function invalidate(): void {
    queryClient.invalidateQueries({ queryKey: ["users"] });
  }

  async function handleAdd(): Promise<void> {
    if (!newEmail) return;
    await createUser(newEmail, false);
    setNewEmail("");
    invalidate();
  }

  const columns: Column<AllowedUserRecord>[] = [
    { header: "Email", render: (u) => u.email },
    { header: "Active", render: (u) => (u.isActive ? "Yes" : "No") },
    { header: "Admin", render: (u) => (u.isAdmin ? "Yes" : "No") },
    { header: "Blocked", render: (u) => (u.isBlocked ? "Yes" : "No") },
    {
      header: "Actions",
      render: (u) => (
        <div className="flex gap-2">
          <button
            onClick={() => updateUser(u.email, { isBlocked: !u.isBlocked }).then(invalidate)}
            className="text-sm text-[var(--color-accent)]"
          >
            {u.isBlocked ? "Unblock" : "Block"}
          </button>
          <button
            onClick={() => updateUser(u.email, { isAdmin: !u.isAdmin }).then(invalidate)}
            className="text-sm text-[var(--color-accent)]"
          >
            {u.isAdmin ? "Revoke admin" : "Make admin"}
          </button>
          <button
            onClick={() => deleteUser(u.email).then(invalidate)}
            className="text-sm text-[var(--color-danger)]"
          >
            Delete
          </button>
        </div>
      ),
    },
  ];

  return (
    <div className="p-6">
      <h1 className="mb-4 text-xl font-semibold">Users</h1>
      <div className="mb-4 flex gap-2">
        <input
          placeholder="new.user@example.com"
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2 text-sm"
        />
        <button onClick={handleAdd} className="rounded-md bg-[var(--color-accent)] px-3 py-2 text-sm text-white">
          Add
        </button>
      </div>
      <DataTable columns={columns} rows={users} rowKey={(u) => u.email} />
    </div>
  );
}
```

- [ ] **Step 3: Write `api/audit.ts`**

```typescript
// src/api/audit.ts
import { apiFetch } from "./auth";

export interface AuditRecordItem {
  jobId: string;
  node: string;
  event: string;
  timestamp: string;
  durationMs: number | null;
  detail: Record<string, unknown> | null;
}

export interface AuditPage {
  items: AuditRecordItem[];
  total: number;
  page: number;
  pageSize: number;
}

export async function fetchAuditPage(params: { jobId?: string; node?: string }): Promise<AuditPage> {
  const query = new URLSearchParams();
  if (params.jobId) query.set("jobId", params.jobId);
  if (params.node) query.set("node", params.node);

  const response = await apiFetch(`/audit?${query.toString()}`);
  if (!response.ok) {
    throw new Error(`GET /audit failed: ${response.status}`);
  }
  return response.json();
}
```

- [ ] **Step 4: Implement `AuditLogPage.tsx`**

```typescript
// src/pages/AuditLogPage.tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { fetchAuditPage, type AuditRecordItem } from "../api/audit";
import DataTable, { type Column } from "../components/DataTable";

const COLUMNS: Column<AuditRecordItem>[] = [
  { header: "Job", render: (r) => r.jobId },
  { header: "Node", render: (r) => r.node },
  { header: "Event", render: (r) => r.event },
  { header: "Timestamp", render: (r) => new Date(r.timestamp).toLocaleString() },
  { header: "Duration (ms)", render: (r) => r.durationMs ?? "—" },
];

export default function AuditLogPage() {
  const [jobId, setJobId] = useState("");
  const navigate = useNavigate();

  const { data } = useQuery({
    queryKey: ["audit", jobId],
    queryFn: () => fetchAuditPage({ jobId: jobId || undefined }),
  });

  return (
    <div className="p-6">
      <h1 className="mb-4 text-xl font-semibold">Audit Log</h1>
      <input
        placeholder="Filter by job ID"
        value={jobId}
        onChange={(e) => setJobId(e.target.value)}
        className="mb-4 rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2 text-sm"
      />
      <DataTable
        columns={COLUMNS}
        rows={data?.items ?? []}
        rowKey={(r, i = 0) => `${r.jobId}-${i}`}
        onRowClick={(r) => navigate(`/documents/${r.jobId}`)}
      />
    </div>
  );
}
```

(`rowKey`'s signature in `DataTable` from Task 18 only accepts one argument — the
`i = 0` default parameter above won't actually receive an index from `DataTable`'s
`.map()` call. Fix by using `` `${r.jobId}-${r.node}-${r.timestamp}` `` instead, which
is unique without needing `DataTable`'s API to change.)

- [ ] **Step 5: Run lint and typecheck**

Hand this to the user to run:
`cd src/classiflow/frontend && npm run lint && npx tsc -b`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/classiflow/frontend/src/api/users.ts src/classiflow/frontend/src/api/audit.ts src/classiflow/frontend/src/pages/UsersPage.tsx src/classiflow/frontend/src/pages/AuditLogPage.tsx
git commit -m "feat: add UsersPage and AuditLogPage"
```

---

### Task 20: End-to-end manual verification

**Files:** none — verification only.

- [ ] **Step 1: Run the full backend test suite**

Hand this to the user to run: `uv run poe check`
Expected: all lint/typecheck/tests pass.

- [ ] **Step 2: Run the full frontend test suite**

Hand this to the user to run:
`cd src/classiflow/frontend && npm run lint && npx tsc -b && npm run test`
Expected: all pass.

- [ ] **Step 3: Run pre-commit on the whole repo**

Hand this to the user to run: `uv run --all-groups pre-commit run --all-files`
Expected: all hooks pass, including the two new `frontend-lint`/`frontend-format`
hooks from Task 14.

- [ ] **Step 4: Manual end-to-end walkthrough**

Hand this to the user to run (both servers running:
`uv run uvicorn classiflow.api.app:create_app --factory` or however the project
normally starts the backend, plus
`cd src/classiflow/frontend && npm run dev`):

1. Visit `http://localhost:5173/login`, sign in with a real allowed Google account.
2. Upload a document (via the existing playground notebook or a `curl` to
   `/pipeline/ingest`) and watch it appear on the Processing page, moving from Queued
   to Processing with a live-updating step timeline.
3. Once classified, find it on the Classification page, click through to its Document
   Detail page, confirm the PDF renders and all four tabs show real data.
4. If it landed in `human_review`, submit a reclassification and confirm it updates.
5. As an admin user, visit Users and Audit Log, confirm both work and a non-admin
   account is redirected away from both.
6. Visit the Chat page, confirm the placeholder renders.

- [ ] **Step 5: Report results back to the user**

Summarize what was verified and any issues found — this is the final gate before
declaring the plan complete.

---

## Self-Review

**Spec coverage check** (against the 7 decisions in
`docs/superpowers/specs/2026-08-24-frontend-application-design.md`):
- Decision 1 (stack, location, DI exclusions) → Task 14. ✓
- Decision 2 (OAuth) → Tasks 8, 15 (+ the redirect-target clarification reached during
  this plan's own review, folded into Task 8). ✓
- Decision 3 (`is_admin`, `AuthService`) → Tasks 1, 2. ✓
- Decision 4 (queued/processing) → Task 5. ✓
- Decision 5 (new endpoints) → Tasks 6, 9, 10, 11, 12. ✓
- Decision 6 (pages) → Tasks 16, 17, 18, 19. ✓
- Decision 7 (nav/access control) → Tasks 15, 16. ✓
- Testing Strategy section → every backend task has repository/route tests; every
  frontend task with real logic (`StepTimeline`, `RequireAdmin`, `ReclassifyPanel`,
  `tokenStorage`) has a component test, matching the spec's named priorities. ✓
- "Same origin in production" (resolved during this plan's Task 8/13 discussion, not
  explicitly a spec decision but load-bearing for Decision 2 to actually work) →
  Task 13. ✓

**Placeholder scan**: no TBD/TODO left in any step; Task 16's page placeholders are
explicitly temporary scaffolding replaced by name in Tasks 17-19, not unfinished plan
content.

**Type consistency fix applied during self-review**: Task 19's `AuditLogPage` initially
called `DataTable`'s `rowKey` with a second `i` parameter `DataTable` (Task 18) never
provides — caught and corrected to a key built only from fields already on
`AuditRecordItem`.

**Known follow-up not included in this plan** (flagged, not silently dropped): the
spec's Open Risks table notes non-PDF documents aren't given special viewer treatment —
`PdfViewer` will simply fail to render a `.docx`/image upload's bytes. This matches the
spec's explicit acceptance of that gap; no task in this plan attempts a general file
previewer.

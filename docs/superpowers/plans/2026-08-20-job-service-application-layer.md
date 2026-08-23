# JobService Application Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the orchestration currently scattered across three `pipeline/endpoints.py` route handlers into one `JobService` application service, so route handlers depend on a service instead of raw repositories directly.

**Architecture:** A new `JobService` (mirroring `AuditService`'s existing shape: one class, injected repos, real methods) wraps `IJobRepository`/`IDocumentStepsRepository`/`IHumanDecisionRepository`. `JobNotFoundError`/`JobNotInReviewError` move alongside it into a new `services/job/` package. Route handlers switch from injecting 1-2 raw repos to injecting one `JobService`; DI wiring (`api/dependencies.py`, `injections/test.py`, `tests/api/conftest.py`) is updated to match. `IHashRepository`/`IEnrichedRecordRepository`/`IClassificationRecordRepository` are explicitly out of scope — their consumers (LangGraph nodes, `PipelineService`) already are the orchestrating layer.

**Tech Stack:** Pydantic (`BaseEntity` — not used here, `JobService` is a plain `__init__` service per this project's `__init__` vs `BaseModel` convention), `dependency_injector`, FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-job-service-application-layer-design.md`

## Global Constraints

- Line length 100, double-quote strings (ruff-enforced).
- mypy strict: never use `Any`. Never use `from __future__ import annotations` — quote forward references (`"MyType"`) instead. Never use `TYPE_CHECKING` unless avoiding a real circular import.
- Services (hold injected dependencies) → plain `__init__`, never `BaseModel`/`BaseEntity`.
- Exceptions: each service gets its own `exceptions.py` — a plain base class (`class XError(Exception): ...`) plus `@dataclass` subclasses that call `super().__init__(str(self))` in `__post_init__` and define `__str__`. Never raise the base directly.
- `__init__.py` files contain only re-exports and `__all__` — no executable statements.
- `uv run poe check` is the project's single verification gate. **Do not run it yourself** — hand the exact command to the user and wait. Plain `pytest tests/path::test -v` runs during the test-first loop are fine to run directly.
- Git: never `git add`, `git commit`, `git push`, or open a PR without the user's explicit go-ahead in that message.
- All comments/docstrings/commit messages in English.

---

## Task 1: `JobService` + `services/job/exceptions.py`

Create the new `services/job/` package mirroring `services/audit/`'s shape. `JobNotFoundError`/`JobNotInReviewError` move here from `services/pipeline/exceptions.py` (they are job-service errors — `PipelineService` never raises either today). `JobService` wraps three existing repos with three methods, each lifted from `api/routes/pipeline/endpoints.py`'s current handler bodies (`get_job` from `pipeline_events`'s existence check, `list_review_queue` from `review_queue`'s loop, `submit_decision` from `submit_decision`'s body verbatim).

**Files:**
- Create: `src/classiflow/services/job/__init__.py`
- Create: `src/classiflow/services/job/exceptions.py`
- Create: `src/classiflow/services/job/service.py`
- Create: `tests/shared/test_job_service.py`

**Interfaces:**
- Consumes: `classiflow.domain.repositories.job.IJobRepository`, `classiflow.domain.repositories.document_steps.IDocumentStepsRepository`, `classiflow.domain.repositories.human_decision.IHumanDecisionRepository`, `classiflow.database.models.{Job, DocumentStep, HumanDecision}`, `classiflow.database.repositories.job.InMemoryJobRepository`, `classiflow.database.repositories.document_steps.InMemoryDocumentStepsRepository`, `classiflow.database.repositories.human_decision.InMemoryHumanDecisionRepository`.
- Produces: `classiflow.services.job.exceptions.{JobError, JobNotFoundError, JobNotInReviewError}`. `JobService(job_repo, document_steps_repo, human_decision_repo)` — `async get_job(job_id: str) -> Job | None`, `async list_review_queue() -> list[tuple[Job, list[DocumentStep]]]`, `async submit_decision(job_id: str, *, decided_by: str, decision: str, notes: str | None) -> None` (raises `JobNotFoundError`/`JobNotInReviewError`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/shared/test_job_service.py
from datetime import datetime, timezone

import pytest

from classiflow.database.models import DocumentStep, Job
from classiflow.database.repositories.document_steps import InMemoryDocumentStepsRepository
from classiflow.database.repositories.human_decision import InMemoryHumanDecisionRepository
from classiflow.database.repositories.job import InMemoryJobRepository
from classiflow.services.job.exceptions import JobNotFoundError, JobNotInReviewError
from classiflow.services.job.service import JobService

pytestmark = pytest.mark.anyio


def _service() -> tuple[
    JobService,
    InMemoryJobRepository,
    InMemoryDocumentStepsRepository,
    InMemoryHumanDecisionRepository,
]:
    job_repo = InMemoryJobRepository()
    steps_repo = InMemoryDocumentStepsRepository()
    decision_repo = InMemoryHumanDecisionRepository()
    return JobService(job_repo, steps_repo, decision_repo), job_repo, steps_repo, decision_repo


def _job(job_id: str, status: str) -> Job:
    now = datetime.now(timezone.utc)
    return Job(job_id=job_id, filename="doc.pdf", status=status, created_at=now, updated_at=now)


async def test_get_job_returns_the_job() -> None:
    service, job_repo, _, _ = _service()
    await job_repo.create(_job("job-1", "started"))

    result = await service.get_job("job-1")

    assert result is not None
    assert result.job_id == "job-1"


async def test_get_job_returns_none_for_missing_job() -> None:
    service, _, _, _ = _service()

    assert await service.get_job("missing") is None


async def test_list_review_queue_filters_to_review_status_and_includes_steps() -> None:
    service, job_repo, steps_repo, _ = _service()
    await job_repo.create(_job("job-review", "review"))
    await job_repo.create(_job("job-accepted", "accepted"))
    await steps_repo.save_step(
        DocumentStep(
            job_id="job-review",
            step_order=1,
            node="node1_file_reception",
            status="passed",
            passed=True,
            timestamp=datetime.now(timezone.utc),
        )
    )

    queue = await service.list_review_queue()

    assert len(queue) == 1
    job, steps = queue[0]
    assert job.job_id == "job-review"
    assert len(steps) == 1
    assert steps[0].node == "node1_file_reception"


async def test_submit_decision_raises_when_job_missing() -> None:
    service, _, _, _ = _service()

    with pytest.raises(JobNotFoundError):
        await service.submit_decision(
            "missing", decided_by="reviewer@x.com", decision="accept", notes=None
        )


async def test_submit_decision_raises_when_job_not_in_review() -> None:
    service, job_repo, _, _ = _service()
    await job_repo.create(_job("job-1", "accepted"))

    with pytest.raises(JobNotInReviewError):
        await service.submit_decision(
            "job-1", decided_by="reviewer@x.com", decision="accept", notes=None
        )


async def test_submit_decision_saves_decision_and_updates_status() -> None:
    service, job_repo, _, decision_repo = _service()
    await job_repo.create(_job("job-1", "review"))

    await service.submit_decision(
        "job-1", decided_by="reviewer@x.com", decision="accept", notes="looks good"
    )

    job = await job_repo.find_by_job_id("job-1")
    assert job is not None
    assert job.status == "accepted"
    decisions = await decision_repo.decisions_for_job("job-1")
    assert len(decisions) == 1
    assert decisions[0].decided_by == "reviewer@x.com"
    assert decisions[0].notes == "looks good"


async def test_submit_decision_reject_sets_rejected_status() -> None:
    service, job_repo, _, _ = _service()
    await job_repo.create(_job("job-1", "review"))

    await service.submit_decision(
        "job-1", decided_by="reviewer@x.com", decision="reject", notes=None
    )

    job = await job_repo.find_by_job_id("job-1")
    assert job is not None
    assert job.status == "rejected"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/shared/test_job_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'classiflow.services.job'`

- [ ] **Step 3: Implement `services/job/exceptions.py`**

```python
# src/classiflow/services/job/exceptions.py
from dataclasses import dataclass


class JobError(Exception): ...


@dataclass
class JobNotFoundError(JobError):
    job_id: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Job {self.job_id} not found"


@dataclass
class JobNotInReviewError(JobError):
    job_id: str
    status: str

    def __post_init__(self) -> None:
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Job {self.job_id} is not in review (status={self.status})"
```

- [ ] **Step 4: Implement `services/job/service.py`**

```python
# src/classiflow/services/job/service.py
from classiflow.database.models import DocumentStep, HumanDecision, Job
from classiflow.domain.repositories.document_steps import IDocumentStepsRepository
from classiflow.domain.repositories.human_decision import IHumanDecisionRepository
from classiflow.domain.repositories.job import IJobRepository
from classiflow.services.job.exceptions import JobNotFoundError, JobNotInReviewError

_DECISION_TO_STATUS = {"accept": "accepted", "reject": "rejected", "escalate": "escalated"}


class JobService:
    def __init__(
        self,
        job_repo: IJobRepository,
        document_steps_repo: IDocumentStepsRepository,
        human_decision_repo: IHumanDecisionRepository,
    ) -> None:
        self._job_repo = job_repo
        self._document_steps_repo = document_steps_repo
        self._human_decision_repo = human_decision_repo

    async def get_job(self, job_id: str) -> Job | None:
        return await self._job_repo.find_by_job_id(job_id)

    async def list_review_queue(self) -> list[tuple[Job, list[DocumentStep]]]:
        jobs = [j for j in await self._job_repo.list_all() if j.status == "review"]
        return [(job, await self._document_steps_repo.steps_for_job(job.job_id)) for job in jobs]

    async def submit_decision(
        self, job_id: str, *, decided_by: str, decision: str, notes: str | None
    ) -> None:
        job = await self._job_repo.find_by_job_id(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        if job.status != "review":
            raise JobNotInReviewError(job_id, job.status)
        await self._human_decision_repo.save(
            HumanDecision(job_id=job_id, decided_by=decided_by, decision=decision, notes=notes)
        )
        await self._job_repo.update_status(job_id, _DECISION_TO_STATUS[decision])
```

- [ ] **Step 5: Implement `services/job/__init__.py`**

```python
# src/classiflow/services/job/__init__.py
from classiflow.services.job.exceptions import JobError, JobNotFoundError, JobNotInReviewError
from classiflow.services.job.service import JobService

__all__ = ["JobError", "JobNotFoundError", "JobNotInReviewError", "JobService"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/shared/test_job_service.py -v`
Expected: PASS (8 tests)

- [ ] **Step 7: Commit**

```bash
git add src/classiflow/services/job/ tests/shared/test_job_service.py
git commit -m "feat: add JobService application layer"
```

---

## Task 2: Remove `JobNotFoundError`/`JobNotInReviewError` from `services/pipeline/`

`services/pipeline/exceptions.py` currently defines the two exceptions Task 1 just re-created under `services/job/`. Remove the duplicates so there is exactly one definition, and update `services/pipeline/__init__.py`'s re-export.

**Files:**
- Modify: `src/classiflow/services/pipeline/exceptions.py`
- Modify: `src/classiflow/services/pipeline/__init__.py`

**Interfaces:**
- Consumes: none new.
- Produces: `classiflow.services.pipeline.exceptions.PipelineError` (unchanged, now with no subclasses defined in this file). `services/pipeline/__init__.py` re-exports only `PipelineService`.

- [ ] **Step 1: Remove the two exception classes from `services/pipeline/exceptions.py`**

Final file content:

```python
# src/classiflow/services/pipeline/exceptions.py
class PipelineError(Exception):
    """Base exception for all pipeline/job-related errors."""
```

- [ ] **Step 2: Update `services/pipeline/__init__.py`**

```python
# src/classiflow/services/pipeline/__init__.py
from classiflow.services.pipeline.service import PipelineService

__all__ = ["PipelineService"]
```

- [ ] **Step 3: Run the full test suite to confirm nothing references the removed classes yet (expected to fail — later tasks fix the remaining references)**

Run: `pytest tests -x -q 2>&1 | head -30`
Expected: FAIL with `ImportError: cannot import name 'JobNotFoundError' from 'classiflow.services.pipeline.exceptions'` (from `api/error_handlers/pipeline.py`, `api/error_handlers/types.py`, and `api/routes/pipeline/endpoints.py` — fixed in Tasks 3-4).

- [ ] **Step 4: Commit**

```bash
git add src/classiflow/services/pipeline/exceptions.py src/classiflow/services/pipeline/__init__.py
git commit -m "refactor: remove JobNotFoundError/JobNotInReviewError from services/pipeline (moved to services/job)"
```

---

## Task 3: Update error handlers to import from `services/job`

`api/error_handlers/pipeline.py` and `api/error_handlers/types.py` both import `JobNotFoundError`/`JobNotInReviewError` from the now-empty `services.pipeline.exceptions`. Point both at `services.job.exceptions` instead.

**Files:**
- Modify: `src/classiflow/api/error_handlers/pipeline.py`
- Modify: `src/classiflow/api/error_handlers/types.py`

**Interfaces:**
- Consumes: `classiflow.services.job.exceptions.{JobNotFoundError, JobNotInReviewError}` (Task 1).
- Produces: no new symbols — same `handle_job_not_found_error`/`handle_job_not_in_review_error`/`EXCEPTION_HANDLERS` as before, just re-pointed imports.

- [ ] **Step 1: Update `api/error_handlers/pipeline.py`'s import**

Change:
```python
from classiflow.services.pipeline.exceptions import JobNotFoundError, JobNotInReviewError
```
to:
```python
from classiflow.services.job.exceptions import JobNotFoundError, JobNotInReviewError
```

Rest of the file (the two handler functions) is unchanged.

- [ ] **Step 2: Update `api/error_handlers/types.py`'s import**

Change:
```python
from classiflow.services.pipeline.exceptions import JobNotFoundError, JobNotInReviewError
```
to:
```python
from classiflow.services.job.exceptions import JobNotFoundError, JobNotInReviewError
```

Rest of the file (the `EXCEPTION_HANDLERS` dict) is unchanged — the dict's keys are the same class objects, now imported from their new home.

- [ ] **Step 3: Run the API error-handler tests to confirm imports resolve**

Run: `pytest tests/api -k "error_handler or not_found or not_in_review" -v`
Expected: PASS (or no matching tests collected — either is fine; the real check is the next step's import-resolution).

Run: `python -c "from classiflow.api.error_handlers.types import EXCEPTION_HANDLERS; print('ok')"`
Expected: prints `ok` with no `ImportError`.

- [ ] **Step 4: Commit**

```bash
git add src/classiflow/api/error_handlers/pipeline.py src/classiflow/api/error_handlers/types.py
git commit -m "refactor: point error handlers at services.job.exceptions"
```

---

## Task 4: Wire `JobService` into `api/dependencies.py` and `pipeline/endpoints.py`

Add `get_job_service` to `api/dependencies.py`, then switch all three route handlers in `pipeline/endpoints.py` to depend on it instead of raw repos.

**Files:**
- Modify: `src/classiflow/api/dependencies.py`
- Modify: `src/classiflow/api/routes/pipeline/endpoints.py`

**Interfaces:**
- Consumes: `classiflow.services.job.service.JobService` (Task 1), `classiflow.services.job.exceptions.{JobNotFoundError, JobNotInReviewError}` (Task 1).
- Produces: `get_job_service(job_repo, document_steps_repo, human_decision_repo) -> JobService` in `api/dependencies.py`. Route handlers unchanged in URL/request/response shape.

- [ ] **Step 1: Add `get_job_service` to `api/dependencies.py`**

Add the import (alongside the existing `from classiflow.services.pipeline.service import PipelineService` line):

```python
from classiflow.services.job.service import JobService
```

Add the function immediately after `get_human_decision_repo` (before `get_hash_repo`):

```python
def get_job_service(
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    document_steps_repo: Annotated[IDocumentStepsRepository, Depends(get_document_steps_repo)],
    human_decision_repo: Annotated[IHumanDecisionRepository, Depends(get_human_decision_repo)],
) -> JobService:
    return JobService(job_repo, document_steps_repo, human_decision_repo)
```

`get_job_repo`/`get_document_steps_repo`/`get_human_decision_repo` themselves are **not removed** — `get_job_service` depends on them via `Depends()`, and `get_pipeline_service` still depends on `get_job_repo`/`get_document_steps_repo` directly (unchanged, since `PipelineService` is itself an orchestrator per the spec's Decision table).

- [ ] **Step 2: Update `pipeline/endpoints.py`'s imports**

Replace:
```python
from classiflow.api.dependencies import (
    CurrentUser,
    get_current_user,
    get_document_steps_repo,
    get_human_decision_repo,
    get_job_repo,
    get_pipeline_service,
)
```
with:
```python
from classiflow.api.dependencies import (
    CurrentUser,
    get_current_user,
    get_job_service,
    get_pipeline_service,
)
```

Replace:
```python
from classiflow.database.models import HumanDecision
from classiflow.domain.repositories.document_steps import IDocumentStepsRepository
from classiflow.domain.repositories.human_decision import IHumanDecisionRepository
from classiflow.domain.repositories.job import IJobRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.injections.production import Container
from classiflow.services.pipeline.exceptions import JobNotFoundError, JobNotInReviewError
from classiflow.services.pipeline.service import PipelineService
```
with:
```python
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.injections.production import Container
from classiflow.services.job.exceptions import JobNotFoundError, JobNotInReviewError
from classiflow.services.job.service import JobService
from classiflow.services.pipeline.service import PipelineService
```

`_DECISION_TO_STATUS` (module-level dict, currently right after `router = APIRouter(...)`) is removed from this file entirely — it now lives in `JobService`.

- [ ] **Step 3: Rewrite `review_queue`**

```python
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
```

- [ ] **Step 4: Rewrite `pipeline_events`**

```python
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
```

- [ ] **Step 5: Rewrite `submit_decision`**

```python
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
```

- [ ] **Step 6: Run the pipeline route tests**

Run: `pytest tests/api/routes/test_pipeline.py -v`
Expected: PASS — same routes, same request/response schemas, same status codes; this task changes only what's injected internally.

- [ ] **Step 7: Commit**

```bash
git add src/classiflow/api/dependencies.py src/classiflow/api/routes/pipeline/endpoints.py
git commit -m "feat: wire JobService into pipeline route handlers"
```

---

## Task 5: Wire `JobService` into `injections/test.py` and `tests/api/conftest.py`

`TestContainer` needs a `job_service` provider so `tests/api/conftest.py` can override `get_job_service` the same way it already overrides `get_job_repo`/`get_document_steps_repo`/`get_human_decision_repo`/`get_pipeline_service`.

**Files:**
- Modify: `src/classiflow/injections/test.py`
- Modify: `tests/api/conftest.py`

**Interfaces:**
- Consumes: `classiflow.services.job.service.JobService` (Task 1), `classiflow.api.dependencies.get_job_service` (Task 4).
- Produces: `TestContainer.job_service` provider. `tests/api/conftest.py`'s `client` fixture overrides `get_job_service`.

- [ ] **Step 1: Add the `job_service` import and provider to `injections/test.py`**

Add the import alongside the existing `from classiflow.services.pipeline.service import PipelineService` line:

```python
from classiflow.services.job.service import JobService
```

Add the provider immediately after the existing `job_repo = providers.Singleton(InMemoryJobRepository)` / `document_steps_repo` / `human_decision_repo` provider block (these three already exist — see lines ~119-121 in the current file), placed right before `audit_service`:

```python
    job_service = providers.Factory(
        JobService,
        job_repo=job_repo,
        document_steps_repo=document_steps_repo,
        human_decision_repo=human_decision_repo,
    )
```

- [ ] **Step 2: Add the override to `tests/api/conftest.py`**

Add the import:

```python
from classiflow.api.dependencies import get_job_service
from classiflow.services.job.service import JobService
```

(merge into the existing `from classiflow.api.dependencies import (...)` block rather than a separate line — add `get_job_service` to that import's existing name list.)

Add the override function alongside the existing four (`_job_repo_override`, `_document_steps_repo_override`, `_human_decision_repo_override`, `_pipeline_service_override`):

```python
    def _job_service_override() -> JobService:
        return test_container.job_service()
```

Add the registration line alongside the existing four:

```python
    app.dependency_overrides[get_job_service] = _job_service_override
```

Leave the existing `_job_repo_override`/`_document_steps_repo_override`/`_human_decision_repo_override` functions and their `dependency_overrides` registrations in place — `get_pipeline_service` still depends on `get_job_repo`/`get_document_steps_repo` directly (Task 4 confirmed this), so those three overrides are still exercised.

- [ ] **Step 3: Run the full API test suite**

Run: `pytest tests/api -v`
Expected: PASS across the board.

- [ ] **Step 4: Commit**

```bash
git add src/classiflow/injections/test.py tests/api/conftest.py
git commit -m "feat: wire JobService into TestContainer and API test fixtures"
```

---

## Task 6: Full regression check

Run the complete gate to confirm the whole change set is consistent — no stray references to the old exception location, no broken imports, no behavior change visible at the HTTP layer.

**Files:** none (verification only).

**Interfaces:** none.

- [ ] **Step 1: Grep for any remaining `services.pipeline.exceptions` import of the moved classes**

Run: `grep -rn "from classiflow.services.pipeline.exceptions import" src/ tests/`
Expected: no output, or only imports of `PipelineError` itself (not `JobNotFoundError`/`JobNotInReviewError`).

- [ ] **Step 2: Hand the full gate command to the user**

Hand to the user (per this project's standing convention — do not run yourself):

```bash
uv run poe check
```

Expected: all steps (lint, format, typecheck, test, coverage) pass; `uv run --all-groups pre-commit run --all-files` also passes.

- [ ] **Step 3: Commit** (only if Step 2 required any fixes; otherwise nothing to commit)

```bash
git add -A
git commit -m "fix: resolve full-gate findings from JobService migration"
```

---

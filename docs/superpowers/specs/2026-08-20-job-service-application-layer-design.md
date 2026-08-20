# JobService Application Layer — Design

**Date:** 2026-08-20
**Status:** Approved for planning

## Context

`api/routes/pipeline/endpoints.py`'s three read/write route handlers
(`review_queue`, `pipeline_events`, `submit_decision`) each inject one or two
thin repositories (`IJobRepository`, `IDocumentStepsRepository`,
`IHumanDecisionRepository`) directly via FastAPI `Depends()`, and perform
their own orchestration inline — a list comprehension + per-job step lookup
in `review_queue`, an existence check in `pipeline_events`, and an
existence-check + status-guard + two writes in `submit_decision`. Per this
project's `ddd-python` skill, that orchestration belongs in an application
service, not scattered across route bodies.

This mirrors a question raised while reviewing Task 16 of the Stage 4
classification-routing plan: `get_classification_record_repo(session: DbSession)`
constructs `SqlClassificationRecordRepository` directly, the same pattern the
five other `get_*_repo` functions in `api/dependencies.py` already use. The
one existing exception is `get_audit_service`, which wraps `SqlAuditRepository`
in `AuditService` because `AuditService` has real behavior beyond CRUD
(field validation, timestamped record construction, logging). This design
generalizes that same test — *does a service have real content to hold* —
across the other five repos, rather than assuming every repo needs a service
wrapper reflexively.

## Decision: which repos get a service, and why

Applying the `AuditService` test to each of the six thin repos in this
codebase:

| Repo | Consumed by | Orchestration exists today? | Gets a service? |
|---|---|---|---|
| `IJobRepository` | `pipeline/endpoints.py` route handlers | Yes — `review_queue`, `pipeline_events`, `submit_decision` | **Yes** |
| `IDocumentStepsRepository` | `pipeline/endpoints.py` route handlers | Yes — `review_queue` | **Yes** |
| `IHumanDecisionRepository` | `pipeline/endpoints.py` route handlers | Yes — `submit_decision` | **Yes** |
| `IHashRepository` | `DuplicateControlNode` (a LangGraph node) | The node itself is the orchestrator | No — unchanged |
| `IEnrichedRecordRepository` | `PipelineService` | `PipelineService` itself is the orchestrator | No — unchanged |
| `IClassificationRecordRepository` | `RoutingNode`; Task 17's not-yet-built human-review endpoint (already designed to call `RoutingNode.run()` directly, not a service) | `RoutingNode` itself is the orchestrator | No — unchanged |

The first three are consumed **directly by HTTP route handlers**, which have
no other natural orchestration home — that's exactly the gap an application
service fills. The last three are consumed by **LangGraph nodes or
`PipelineService`**, which already are the orchestrating layer for that
data; wrapping their one repo in a service would insert a layer between the
DI container and the orchestrator with nothing of its own to do — a Middle
Man (`code-smells` catalog). Task 17's own plan (already written,
pre-dating this design) independently arrived at the same conclusion:
`RoutingNode` and `get_classification_record_repo` are consumed directly,
not through a service.

**Net effect on the question that started this**:
`get_classification_record_repo(session: DbSession) -> IClassificationRecordRepository`
was correct as written and does not change.

## Design: `JobService`

One service, not three, mirroring `AuditService`'s shape (one class per
cohesive orchestration need) rather than one-service-per-repo. `review_queue`
and `submit_decision` already treat "a job and its related records" as one
conceptual unit — splitting into `JobService`/`DocumentStepsService`/
`HumanDecisionService` would just move the same cross-repo orchestration from
route handlers into a still-needed fourth coordinating layer, adding a hop
without removing one.

```python
# src/classiflow/services/job/service.py
class JobService:
    def __init__(
        self,
        job_repo: IJobRepository,
        document_steps_repo: IDocumentStepsRepository,
        human_decision_repo: IHumanDecisionRepository,
    ) -> None:
        self._jobs = job_repo
        self._steps = document_steps_repo
        self._decisions = human_decision_repo

    async def get_job(self, job_id: str) -> Job | None:
        """Used by pipeline_events' existence check."""
        return await self._jobs.find_by_job_id(job_id)

    async def list_review_queue(self) -> list[tuple[Job, list[DocumentStep]]]:
        """Lifted from review_queue's current loop -- returns domain types,
        not the API's ReviewQueueItem schema. The route handler stays
        responsible for building the response schema; the service stays
        schema-agnostic, matching this project's existing layering (compare
        RoutingNode returning RoutingResult, not an API response model)."""
        jobs = [j for j in await self._jobs.list_all() if j.status == "review"]
        return [(job, await self._steps.steps_for_job(job.job_id)) for job in jobs]

    async def submit_decision(
        self, job_id: str, *, decided_by: str, decision: str, notes: str | None
    ) -> None:
        """Lifted from submit_decision's current body verbatim (existence
        check, status guard, decision save, status update)."""
        job = await self._jobs.find_by_job_id(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        if job.status != "review":
            raise JobNotInReviewError(job_id, job.status)
        await self._decisions.save(
            HumanDecision(job_id=job_id, decided_by=decided_by, decision=decision, notes=notes)
        )
        await self._jobs.update_status(job_id, _DECISION_TO_STATUS[decision])
```

`_DECISION_TO_STATUS` moves from `endpoints.py` into `service.py` alongside
the logic that uses it.

### Exceptions

`JobNotFoundError`/`JobNotInReviewError` move from
`services/pipeline/exceptions.py` to `services/job/exceptions.py` — they are
job-service errors (raised by `JobService.submit_decision`, not by
`PipelineService`, which never raises either today). Same
`@dataclass`-subclass-of-a-plain-base shape this project's exception
convention already requires; `PipelineError` in `services/pipeline/exceptions.py`
keeps whatever it already has (nothing currently depends on
`JobNotFoundError`/`JobNotInReviewError` being under `PipelineError`
specifically — both route handlers and error handlers catch them by their
own concrete type). Two files under `api/error_handlers/` import
`JobNotFoundError`/`JobNotInReviewError` from `services.pipeline.exceptions`
today and must switch to `services.job.exceptions`:
`api/error_handlers/pipeline.py` (the two `handle_job_*` functions'
`isinstance` assertions) and `api/error_handlers/types.py` (the
`EXCEPTION_HANDLERS` dict's keys). Whether `pipeline.py` itself should be
renamed to `job.py` to match is a naming call for the implementation plan,
not settled here.

## DI wiring changes

**`api/dependencies.py`**: add

```python
def get_job_service(
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    document_steps_repo: Annotated[IDocumentStepsRepository, Depends(get_document_steps_repo)],
    human_decision_repo: Annotated[IHumanDecisionRepository, Depends(get_human_decision_repo)],
) -> JobService:
    return JobService(job_repo, document_steps_repo, human_decision_repo)
```

`get_job_repo`/`get_document_steps_repo`/`get_human_decision_repo` are
**kept**, not removed — `get_job_service` depends on them the same way
`get_audit_service` already depends on `get_hash_repo`-style raw-session
construction internally. (Confirmed no other call site depends on the three
repo getters directly once route handlers switch to `get_job_service` — the
only other consumer is `get_pipeline_service`'s own `job_repo`/
`document_steps_repo` params, which stay as-is since `PipelineService` is
itself an orchestrator, per the table above.)

**`api/routes/pipeline/endpoints.py`**: `review_queue`, `pipeline_events`,
`submit_decision` switch from injecting 1-2 raw repos to injecting one
`JobService`. Each handler body shrinks to a `JobService` call plus (for
`review_queue`) the existing `ReviewQueueItem`-schema-building loop, now
iterating the service's returned `(Job, list[DocumentStep])` tuples instead
of doing its own repo calls.

**`injections/test.py`**: add

```python
job_service = providers.Factory(
    JobService, job_repo=job_repo, document_steps_repo=document_steps_repo,
    human_decision_repo=human_decision_repo,
)
```

mirroring the existing `audit_service = providers.Factory(AuditService, repo=audit_repo)`
line exactly.

**`tests/api/conftest.py`**: this fixture uses FastAPI's own
`app.dependency_overrides` mechanism for `job_repo`/`document_steps_repo`/
`human_decision_repo`/`pipeline_service` specifically (not
`container.override()`) because these are session-scoped, built per-request
from a native `Depends(get_session)` in production rather than from the
`dependency_injector` `Container` — see the fixture's own existing comment.
Add a `_job_service_override() -> JobService: return test_container.job_service()`
function plus `app.dependency_overrides[get_job_service] = _job_service_override`,
matching the existing four. Once route handlers stop depending on
`get_job_repo`/`get_document_steps_repo`/`get_human_decision_repo` directly
(switching to `get_job_service` only), check during implementation whether
those three now-unused overrides should be removed from this fixture or kept
for hypothetical future direct-repo test needs — a small cleanup call, not
decided here.

## Testing

New `tests/shared/test_job_service.py`, mirroring
`tests/shared/test_repositories.py`'s style: `InMemoryJobRepository` +
`InMemoryDocumentStepsRepository` + `InMemoryHumanDecisionRepository` wired
into a real `JobService`, asserting `list_review_queue` filters to
`status == "review"` and includes each job's steps, `submit_decision` raises
`JobNotFoundError`/`JobNotInReviewError` correctly and performs both writes
on success, `get_job` returns `None` for a missing job.

`tests/api/routes/test_pipeline.py` is unaffected — it already tests through
the HTTP layer, which doesn't change shape (same routes, same request/response
schemas, same status codes).

## Non-goals

- `IHashRepository`, `IEnrichedRecordRepository`, `IClassificationRecordRepository`
  do **not** get service wrappers — see the Decision table above.
- No change to `RoutingNode`, `DuplicateControlNode`, or `PipelineService`'s
  constructors or bodies.
- No change to `api/dependencies.py`'s `get_classification_record_repo`,
  `get_hash_repo`, or `get_enriched_record_repo` — all three stay exactly as
  written.
- Task 17 (human-review decision API, not yet implemented) is unaffected by
  this design and should proceed exactly as already planned (direct
  `get_classification_record_repo`/`get_routing` injection, no service
  layer) once this JobService work lands.

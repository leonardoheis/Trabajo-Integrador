# Classiflow — Task List

> One task = one worktree branch = one PR.
> Full task details are in [plan.md](plan.md).
> Status: `[ ]` pending · `[~]` in progress · `[x]` done · `[-]` skipped for now · `[!]` blocked

---

## Parallel Execution Map

```
BATCH 0  ──────────────────────────────────────────────── sequential
  T01  Package skeleton + dependencies

BATCH 1  ──────────────────────────────────────────────── parallel (all need T01)
  T02  Database models + Alembic
  T04  JWT utilities                     [-] skipped for now
  T18  GitHub Actions CI                 [-] skipped for now

BATCH 2  ──────────────────────────────────────────────── sequential (needs T02)
  T03  Repository implementations

BATCH 3  ──────────────────────────────────────────────── sequential (needs T03)
  T07  Shared domain + AuditService + EventBroadcaster

BATCH 4  ──────────────────────────────────────────────── parallel
  T05  Google OAuth + whitelist          (needs T03 + T04)
  T08  Ingesta domain models             (needs T07)

BATCH 5  ──────────────────────────────────────────────── sequential (needs T04 + T05)
  T06  JWT auth middleware

BATCH 6  ──────────────────────────────────────────────── sequential (needs T08)
  T09  Agent 1 — File Reception

BATCH 7  ──────────────────────────────────────────────── sequential (needs T09)
  T10  Agent 2 — Format Validation (rule-based)

BATCH 8  ──────────────────────────────────────────────── parallel
  T11  LLM Provider singleton            (needs T01)
  T14  Agent 4 — Duplicate Control       (needs T03 + T07 + T08)

BATCH 9  ──────────────────────────────────────────────── parallel
  T12  Agent 2 — SLM escalation path     (needs T10 + T11)
  T13  Agent 3 — Content Validation      (needs T07 + T08 + T11)

BATCH 10  ─────────────────────────────────────────────── sequential (needs T09+T12+T13+T14)
  T15  Coordinator — LangGraph

BATCH 11  ─────────────────────────────────────────────── parallel (needs T01)
  T16  FastAPI app + health route

BATCH 12  ─────────────────────────────────────────────── sequential (needs T06+T15+T16)
  T17  Pipeline endpoints + SSE stream

BATCH 13  ─────────────────────────────────────────────── sequential (needs T17)
  T19  Docker build + push CI
```

---

## Task Cards

---

### T01 · Package skeleton + dependencies
**Branch:** `feat/skeleton` · **Deps:** none · **Status:** `[x]` · **PR:** [#2](https://github.com/lgj2911/Trabajo-Integrador/pull/2)

- [x] All `src/classiflow/` subdirs exist with `__init__.py` (api, shared, ingesta + children)
- [x] `config/` with three stub YAMLs (`allowed_formats`, `content_validation`, `duplicate_control`)
- [x] `alembic/` initialized (`alembic init`)
- [x] `tests/ingesta/` and `tests/api/routes/` with `__init__.py`
- [x] All deps in `pyproject.toml` (see plan Phase 1 list)
- [x] `uv sync --dev` succeeds, `uv.lock` updated
- [x] `uv run poe check` passes

> **Note:** `src/classiflow/injections/` skeleton is added in **T16** (FastAPI app) — that is
> where the container implementation lives.

```bash
# Verify
uv run poe check
python -c "from classiflow.api import app; from classiflow.ingesta import agents"
```

---

### T02 · Database models + Alembic migration
**Branch:** `feat/database-models` · **Deps:** T01 · **Status:** `[x]` · **PR:** [#5](https://github.com/lgj2911/Trabajo-Integrador/pull/5)

- [x] `shared/database/base.py`: async engine factory + `get_session()` async generator
- [x] `shared/database/models.py`: six ORM models — `AllowedUser`, `AuditRecord`, `HashRecord`, `Job`, `DocumentStep`, `HumanDecision`
- [x] `Job` model has `failed_at_agent`, `rejection_reason`, `review_action_needed` columns
- [x] `DocumentStep` model: `step_order`, `agent`, `status`, `passed`, `rejection_reason`, `duration_ms`, `detail` (JSON), `timestamp`; FK → `jobs.job_id`
- [x] `HumanDecision` model: `decided_by`, `decision` (`accept`/`reject`/`escalate`), `notes`, `decided_at`; FK → `jobs.job_id`
- [x] `settings.py` has `DATABASE_URL` defaulting to `sqlite+aiosqlite:///./classiflow.db`
- [x] `alembic upgrade head` creates all six tables on a fresh SQLite file
- [x] Switching `DATABASE_URL` to `postgresql+asyncpg://...` requires zero code changes
- [x] `uv run poe check` passes (86 tests, mypy clean)

```bash
# Verify
uv run poe check
alembic upgrade head
python -c "import sqlite3; c=sqlite3.connect('classiflow.db'); print(c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall())"
# → allowed_users, audit_records, hash_records, jobs, document_steps, human_decisions
```

---

### T03 · Repository implementations
**Branch:** `feat/repositories` · **Deps:** T02 · **Status:** `[x]` · **PR:** [#6](https://github.com/lgj2911/Trabajo-Integrador/pull/6)

- [x] `IHashRepository`, `IAuditRepository`, `IUserRepository`, `IDocumentStepsRepository`, `IHumanDecisionRepository` as `Protocol` classes
- [x] `SqlHashRepository`, `SqlAuditRepository`, `SqlUserRepository`, `SqlDocumentStepsRepository`, `SqlHumanDecisionRepository` — SQLAlchemy async
- [x] `InMemoryHashRepository`, `InMemoryAuditRepository`, `InMemoryUserRepository`, `InMemoryDocumentStepsRepository`, `InMemoryHumanDecisionRepository` — tests only
- [x] `IDocumentStepsRepository`: `save_step(step)` and `steps_for_job(job_id) -> list[DocumentStep]`
- [x] `IHumanDecisionRepository`: `save(decision)` and `decisions_for_job(job_id) -> list[HumanDecision]`
- [x] mypy confirms each concrete class satisfies its protocol
- [x] Unit tests against in-memory SQLite (no mocks) — 25 new tests
- [x] `uv run poe check` passes (111 tests, 97% coverage)

```bash
# Verify
uv run poe check
uv run poe test tests/shared/test_repositories.py
```

---

### T04 · JWT utilities
**Branch:** `feat/jwt` · **Deps:** T01 · **Status:** `[x]` · **PR:** [#7](https://github.com/lgj2911/Trabajo-Integrador/pull/7)

- [x] `shared/auth/jwt.py`: `encode_token(email)` → JWT string (PyJWT)
- [x] `decode_token(token)` → payload dict or raises `AuthError`
- [x] `settings.py` has `JWT_SECRET_KEY`, `JWT_EXPIRE_MINUTES`
- [x] Tests: valid token, expired token, tampered signature
- [x] No secrets hardcoded
- [x] `uv run poe check` passes (114 tests, mypy clean)

```bash
# Verify
uv run poe check
uv run poe test tests/api/test_auth.py
```

---

### T05 · Google OAuth flow + whitelist check
**Branch:** `feat/oauth` · **Deps:** T03 · T04 · **Status:** `[ ]`

- [ ] `shared/auth/oauth.py`: `get_authorization_url()` and `exchange_code(code, user_repo)`
- [ ] `GET /auth/login` redirects to Google with `scope=email profile`
- [ ] `GET /auth/callback?code=X` exchanges code, checks `allowed_users`, returns JWT
- [ ] HTTP 403 if email not in whitelist or is blocked
- [ ] Tests use `httpx.MockTransport` — no real Google call
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/api/routes/test_auth.py
```

---

### T06 · JWT auth middleware
**Branch:** `feat/auth-middleware` · **Deps:** T04 · T05 · **Status:** `[ ]`

- [ ] `api/middleware/auth.py`: `require_auth` function returning `User` (registered in `Container`)
- [ ] `CurrentUser = Annotated[User, Depends(Provide[Container.current_user])]` in `dependencies.py`
- [ ] Endpoint functions that use `CurrentUser` decorated with `@inject`
- [ ] HTTP 401 on missing header, invalid token, or expired token
- [ ] `/health` and `/auth/*` explicitly public (no `CurrentUser` dependency)
- [ ] Tests: 401 missing, 401 expired, 200 valid
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/api/
```

---

### T07 · Shared domain + AuditService + EventBroadcaster
**Branch:** `feat/shared-infra` · **Deps:** T03 · **Status:** `[x]` · **PR:** [#8](https://github.com/lgj2911/Trabajo-Integrador/pull/8)

- [x] `shared/domain/job.py`: `AgentEvent(BaseModel)`, `JobStatus(str, Enum)`, `AgentEvent.to_sse()` method
- [x] `shared/domain/user.py`: `User(BaseModel)`, `AuthToken(BaseModel)` — no `@dataclass`
- [x] `shared/audit/service.py`: `AuditService.record(event)` → persists via `IAuditRepository` + loguru line
- [x] `shared/events/broadcaster.py`: `emit()`, `subscribe()` async generator, `close()` with cleanup
- [x] `close()` called in `finally` on SSE disconnect (no queue leak)
- [x] Tests: emit→subscribe round-trip, early disconnect, audit persistence
- [x] `uv run poe check` passes (120 tests, mypy clean)

```bash
# Verify
uv run poe check
uv run poe test tests/shared/
```

---

### T08 · Ingesta domain models
**Branch:** `feat+ingesta-domain` · **Deps:** T07 · **Status:** `[x]` · **PR:** [#11](https://github.com/lgj2911/Trabajo-Integrador/pull/11)

- [x] `ingesta/domain/results.py`: `FileReceptionResult`, `FormatValidationResult`, `ContentValidationResult`, `DuplicateControlResult` — all `BaseModel`, no `@dataclass`
- [x] `ingesta/domain/state.py`: `JobState` TypedDict with all coordinator fields
- [x] No logic, no IO — pure typed data
- [x] mypy strict, no `Any`
- [x] `uv run poe check` passes

```bash
# Verify
uv run poe check
python -c "from classiflow.ingesta.domain.results import FileReceptionResult; FileReceptionResult(passed=True, sha256='abc', detected_mime='application/pdf', file_size_bytes=0, rejection_reason='')"
```

---

### T09 · Agent 1 — File Reception
**Branch:** `feat/agent1` · **Deps:** T07 · T08 · **Status:** `[ ]`

- [ ] `FileReceptionResult(passed=False)` for: missing file, empty file, size > limit
- [ ] `FileReceptionResult(passed=True)` with correct `sha256` + `detected_mime` for valid PDF
- [ ] Emits `agent_started` then `agent_passed`/`agent_failed` via broadcaster
- [ ] Calls `AuditService.record()` with `duration_ms` + `detail` on every run
- [ ] Constructor: `__init__(self, audit: AuditService, broadcaster: EventBroadcaster)`
- [ ] Tests use `InMemory*` — no DB, no filesystem side effects
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_agent1.py
```

---

### T10 · Agent 2 — Format Validation (rule-based)
**Branch:** `feat/agent2-rules` · **Deps:** T07 · T08 · T09 · **Status:** `[ ]`

- [ ] `_rule_based_check()` → `ACCEPT` for `.pdf` (magic bytes `%PDF`)
- [ ] `_rule_based_check()` → `REJECT` for `.html` (disabled in config)
- [ ] `_rule_based_check()` → `MANUAL_REVIEW` for unknown MIME
- [ ] `_rule_based_check()` → `None` (gray zone) for MIME/extension mismatch
- [ ] `_slm_check()` raises `NotImplementedError` (stub until T12)
- [ ] Emits events + records audit on every execution
- [ ] Tests cover all four branches
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_agent2.py -k "rule"
```

---

### T11 · LLM Provider singleton
**Branch:** `feat/llm-provider` · **Deps:** T01 · **Status:** `[ ]`

- [ ] `get_llm()` and `get_llm_langchain()` both `@lru_cache(maxsize=1)`, fully typed
- [ ] Two calls to `get_llm()` return the same instance (tested)
- [ ] `MockLlm` substitutes anywhere `Llama` is expected; returns fixed JSON
- [ ] `llama_cpp` import guarded: `TYPE_CHECKING` + runtime `try/except` with clear error
- [ ] `MockLlm` exposed as a pytest fixture in `tests/ingesta/conftest.py`
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_llm_provider.py
```

---

### T12 · Agent 2 — SLM escalation path
**Branch:** `feat/agent2-slm` · **Deps:** T10 · T11 · **Status:** `[ ]`

- [ ] `ingesta/prompts/format_validation.py`: `FormatDecision(BaseModel)`, `build_format_chain(llm)` → LCEL chain
- [ ] `_slm_check()` replaces `NotImplementedError`, returns `FormatValidationResult(used_slm=True)`
- [ ] Gray-zone end-to-end: `run()` → `_slm_check()` → emits event → records audit
- [ ] Tests use `MockLlm`; no real model
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_agent2.py
```

---

### T13 · Agent 3 — Content Validation
**Branch:** `feat/agent3` · **Deps:** T07 · T08 · T11 · **Status:** `[ ]`

- [ ] `config/content_validation.yaml` has `min_chars` and `allowed_languages`
- [ ] `passed=False` for text shorter than `MIN_CHARS`
- [ ] `passed=False, needs_agent_review=True` for non-Spanish text
- [ ] `passed=True` for valid Spanish text sample
- [ ] `LegitimacyDecision(BaseModel)` matches spec schema
- [ ] `_slm_legitimacy_check()` calls `build_content_chain(llm)` → parsed result
- [ ] Emits events + records audit on every run
- [ ] Tests cover all paths using `MockLlm`
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_agent3.py
```

---

### T14 · Agent 4 — Duplicate Control
**Branch:** `feat/agent4` · **Deps:** T03 · T07 · T08 · **Status:** `[ ]`

- [ ] `config/duplicate_control.yaml` has similarity threshold
- [ ] SHA-256 match → `is_duplicate=True, duplicate_type="exact", similarity_score=1.0`
- [ ] Cosine > threshold → `duplicate_type="semantic"`
- [ ] New document → `is_duplicate=False`, hash saved via `IHashRepository`
- [ ] Constructor: `__init__(self, hash_repo: IHashRepository, audit: AuditService, broadcaster: EventBroadcaster)`
- [ ] Tests use `InMemoryHashRepository` + small FAISS index
- [ ] `sentence-transformers` model load lazy (not at import time)
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_agent4.py
```

---

### T15 · Coordinator — LangGraph state machine
**Branch:** `feat/coordinator` · **Deps:** T09 · T12 · T13 · T14 · **Status:** `[ ]`

- [ ] `JobState` TypedDict with all required fields
- [ ] LangGraph: agent1 → agent2 → agent3 → agent4, conditional edges to `accept`/`reject`/`review`
- [ ] `handle_accept`, `handle_reject`, `handle_review` call `AuditService.record_routing()`
- [ ] `pipeline_done` emitted on every terminal state
- [ ] Integration test: valid PDF → all 4 agents → `accepted`
- [ ] Integration test: empty file → rejected at agent 1
- [ ] Uses `MockLlm` + `InMemory*`; no real model or DB
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_coordinator.py
```

---

### T16 · FastAPI app + health route
**Branch:** `feat/api-app` · **Deps:** T01 · **Status:** `[ ]`

- [ ] `dependency-injector>=4.41` added to `pyproject.toml`; `uv sync --dev` succeeds
- [ ] `src/classiflow/injections/` skeleton: `__init__.py`, `production.py`, `test.py`
- [ ] `injections/production.py`: `Container(DeclarativeContainer)` with `providers.Resource(get_session)`, `providers.Factory` for all `Sql*` repos, `AuditService`, `EventBroadcaster`
- [ ] `injections/test.py`: `TestContainer` overrides every `Sql*` provider with `InMemory*`
- [ ] `injections/__init__.py`: `configure_container()` with `@lru_cache`
- [ ] `api/app.py`: `create_app()` factory calls `configure_container()` and mounts all routers and error handlers
- [ ] `GET /health` → `{"status": "ok"}`, HTTP 200, public
- [ ] `api/schema.py`: `BaseSchema` with camel-case aliases
- [ ] `tests/api/conftest.py`: overrides container with `TestContainer`; `TestClient` fixture + `auth_headers` fixture (bypasses OAuth)
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/api/routes/test_health.py
```

---

### T17 · Pipeline endpoints + SSE stream + review queue
**Branch:** `feat/pipeline-endpoints` · **Deps:** T06 · T15 · T16 · **Status:** `[ ]`

- [ ] `POST /pipeline/ingest` returns HTTP 202 + `job_id` within 100 ms
- [ ] HTTP 401 without valid JWT on all routes
- [ ] Background task starts coordinator without blocking the response
- [ ] `GET /pipeline/{job_id}/events` streams `agent_started`/`agent_passed`/`agent_failed` per agent
- [ ] Final SSE event is `pipeline_done`; stream closes after
- [ ] Client disconnect removes queue (`try/finally` in async generator)
- [ ] HTTP 404 for unknown `job_id`
- [ ] `GET /pipeline/review-queue` returns jobs with `status = REVIEW`, each with inline `document_steps`
- [ ] `POST /pipeline/{job_id}/decision` accepts `{ decision: accept|reject|escalate, notes?: string }`; persists via `IHumanDecisionRepository`; updates `jobs.status`
- [ ] `POST /pipeline/{job_id}/decision` returns HTTP 404 for unknown job, HTTP 409 if job is not in `REVIEW` state
- [ ] Tests assert full SSE sequence using `MockLlm` + small PDF fixture
- [ ] Tests assert review queue contents and decision recording using `InMemory*` repos
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/api/routes/test_pipeline.py
uv run uvicorn classiflow.api.app:create_app --factory --reload
```

---

### T18 · GitHub Actions CI pipeline
**Branch:** `feat/ci` · **Deps:** T01 · **Status:** `[-]` *(skipped for now)*

- [ ] `.github/workflows/ci.yml` triggers on every push and PR
- [ ] Jobs: `lint` (ruff), `typecheck` (mypy), `test` (pytest + coverage), `coverage-gate` (≥ 80%)
- [ ] `lint` and `typecheck` run in parallel
- [ ] `test` uploads coverage artifact
- [ ] All jobs green on first push

```bash
# Verify
gh run list --limit 5
gh run view <run-id>
```

---

### T19 · GitHub Actions Docker build + push
**Branch:** `feat/docker` · **Deps:** T17 · **Status:** `[ ]`

- [ ] `Dockerfile`: `python:3.12-slim`, `apt-get install libmagic1`, `uv sync --no-dev`, port 8000
- [ ] Entrypoint: `uvicorn classiflow.api.app:create_app --factory --host 0.0.0.0 --port 8000`
- [ ] `python-magic` detects MIME correctly inside the container
- [ ] Container accepts `DATABASE_URL`, `JWT_SECRET_KEY`, `GOOGLE_CLIENT_ID/SECRET` as env vars
- [ ] `.github/workflows/docker.yml`: build + push on `main`, build only on PRs
- [ ] `INSTALL.md` documents `libmagic1` for Linux and the Windows dev workaround

```bash
# Verify
docker build -t classiflow .
docker run --env-file .env -p 8000:8000 classiflow
curl http://localhost:8000/health
```

---

## Progress

| Task | Description | Status |
|---|---|---|
| T01 | Package skeleton + dependencies | `[x]` done — PR [#2](https://github.com/lgj2911/Trabajo-Integrador/pull/2) |
| T02 | Database models + Alembic | `[x]` done — PR [#5](https://github.com/lgj2911/Trabajo-Integrador/pull/5) |
| T03 | Repository implementations | `[x]` done — PR [#6](https://github.com/lgj2911/Trabajo-Integrador/pull/6) |
| T04 | JWT utilities | `[x]` done — PR [#7](https://github.com/lgj2911/Trabajo-Integrador/pull/7) |
| T07 | Shared domain + AuditService + EventBroadcaster | `[x]` done — PR [#8](https://github.com/lgj2911/Trabajo-Integrador/pull/8) |
| T08 | Ingesta domain models | `[x]` done — PR [#11](https://github.com/lgj2911/Trabajo-Integrador/pull/11) |
| T05 | Google OAuth + whitelist | `[ ]` pending |
| T06 | JWT auth middleware | `[ ]` pending |
| T09 | Agent 1 — File Reception | `[ ]` pending |
| T10 | Agent 2 — Format Validation (rule-based) | `[ ]` pending |
| T11 | LLM Provider singleton | `[ ]` pending |
| T12 | Agent 2 — SLM escalation path | `[ ]` pending |
| T13 | Agent 3 — Content Validation | `[ ]` pending |
| T14 | Agent 4 — Duplicate Control | `[ ]` pending |
| T15 | Coordinator — LangGraph | `[ ]` pending |
| T16 | FastAPI app + health route | `[ ]` pending |
| T17 | Pipeline endpoints + SSE stream | `[ ]` pending |
| T18 | GitHub Actions CI | `[-]` skipped for now |
| T19 | Docker build + push | `[ ]` pending |

**6 / 19 tasks complete · 1 skipped (T18)**

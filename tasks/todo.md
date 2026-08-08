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
  T09  Node 1 — File Reception

BATCH 7  ──────────────────────────────────────────────── sequential (needs T09)
  T10  Node 2 — Format Validation (rule-based)

BATCH 8  ──────────────────────────────────────────────── parallel
  T11  LLM Provider singleton            (needs T01)
  T14  Node 4 — Duplicate Control        (needs T03 + T07 + T08)

BATCH 9  ──────────────────────────────────────────────── parallel
  T12  Node 2 — SLM escalation path      (needs T10 + T11)
  T13  Node 3 — Content Validation       (needs T07 + T08 + T11)

BATCH 10  ─────────────────────────────────────────────── sequential (needs T09+T12+T13+T14)
  T15  Coordinator — LangGraph

BATCH 11  ─────────────────────────────────────────────── parallel (needs T01)
  T16  FastAPI app + health route

BATCH 12  ─────────────────────────────────────────────── sequential (needs T06+T15+T16)
  T17  Pipeline endpoints + SSE stream

BATCH 13  ─────────────────────────────────────────────── sequential (needs T17)
  T19  Docker build + push CI

BATCH 14  ─────────────────────────────────────────────── parallel (needs T11 + nodes done)
  T20  wandb integration — LLM tracing + per-node metrics
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
python -c "from classiflow.api import app; from classiflow.ingesta import nodes"
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

- [x] `shared/domain/job.py`: `NodeEvent(BaseModel)`, `JobStatus(str, Enum)`, `NodeEvent.to_sse()` method
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

### T09 · Node 1 — File Reception
**Branch:** `feat/agent1` · **Deps:** T07 · T08 · **Status:** `[x]` · **PR:** [#13](https://github.com/lgj2911/Trabajo-Integrador/pull/13)

- [x] `FileReceptionResult(passed=False)` for: missing file, empty file, size > limit
- [x] `FileReceptionResult(passed=True)` with correct `sha256` + `detected_mime` for valid PDF
- [x] Emits `node_started` then `node_passed`/`node_failed` via broadcaster
- [x] Calls `AuditService.record()` with `duration_ms` + `detail` on every run
- [x] Constructor: `__init__(self, audit, broadcaster, mime_detector, max_file_size_bytes)` — `mime_detector` injected so tests run without libmagic; production uses `ingesta/mime.py:detect_mime`
- [x] Tests use `InMemory*` — no DB, no filesystem side effects
- [x] `uv run poe check` passes (138 tests)
- [x] Fixed: removed `configure_container()` from `classiflow/__init__.py` (belongs in `create_app()` per learnings)

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_node1.py
```

---

### T10 · Node 2 — Format Validation (rule-based)
**Branch:** `feat/agent2-rules` · **Deps:** T07 · T08 · T09 · **Status:** `[x]` · **PR:** [#15](https://github.com/lgj2911/Trabajo-Integrador/pull/15)

- [x] `_rule_based_check()` → `ACCEPT` for `.pdf` (magic bytes `%PDF`)
- [x] `_rule_based_check()` → `REJECT` for `.html` (disabled in config)
- [x] `_rule_based_check()` → `MANUAL_REVIEW` for unknown MIME
- [x] `_rule_based_check()` → `None` (gray zone) for MIME/extension mismatch
- [x] `_slm_check()` raises `NotImplementedError` (stub until T12)
- [x] Emits events + records audit on every execution
- [x] Tests cover all four branches (13 tests, 98% coverage)
- [x] `uv run poe check` passes (151 tests)

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_node2.py -k "rule"
```

---

### T11 · LLM Provider singleton
**Branch:** `feat/llm-provider` · **Deps:** T01 · **Status:** `[x]` · **PR:** [#17](https://github.com/lgj2911/Trabajo-Integrador/pull/17) · [#18](https://github.com/lgj2911/Trabajo-Integrador/pull/18)

- [x] `get_llm()` and `get_llm_langchain()` both `@lru_cache(maxsize=1)`, fully typed
- [x] Two calls to `get_llm()` return the same instance (tested)
- [x] `MockLlm` (`BaseLLM` subclass) substitutes anywhere LangChain LLM is expected; returns fixed JSON
- [x] `llama-cpp-python` added as hard dependency; `Llama` imported directly (no `TYPE_CHECKING`)
- [x] `FileNotFoundError` → `ModelNotFoundError`; other failures → `ModelLoadError` (typed exceptions in `ingesta/exceptions.py`)
- [x] API error handlers for `LlmProviderError` hierarchy registered in `EXCEPTION_HANDLERS` (`error_handlers/llm.py`)
- [x] `MockLlm` exposed as a pytest fixture in `tests/ingesta/conftest.py`
- [x] `uv run poe check` passes (160 tests)

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_llm_provider.py
```

---

### T12 · Node 2 — SLM escalation path
**Branch:** `feat/agent2-slm` · **Deps:** T10 · T11 · **Status:** `[x]` · **PR:** [#19](https://github.com/leonardoheis/Trabajo-Integrador/pull/19)

**Model:** Phi-4-mini (GGUF) via `get_llm_langchain()` singleton.
**Strategy:** extend rules first; invoke model only for residual unknowns.

- [x] `allowed_formats.yaml` extended with `known_mismatches` map (common MIME/extension pairs)
- [x] `AllowedFormatsConfig` extended with `known_mismatches: dict[str, list[str]]`
- [x] `_rule_based_check()` consults `known_mismatches` before returning `None`
- [x] `ingesta/prompts/format_validation.py`: `FormatDecisionOutput(BaseModel)`, `build_format_chain(llm)` → LCEL chain
- [x] `_slm_check()` replaces `NotImplementedError`, returns `FormatValidationResult(used_slm=True)`
- [x] Gray-zone end-to-end: rules → (if still None) → `_slm_check()` → emits event → records audit
- [x] Tests use `MockLlm`; no real model (163 tests, all passing)
- [x] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_node2.py
```

---

### T13 · Node 3 — Content Validation
**Branch:** `feat/agent3` · **Deps:** T07 · T08 · T11 · **Status:** `[x]` · **PR:** [#1](https://github.com/leonardoheis/Trabajo-Integrador/pull/1)

**Model:** Phi-4-mini (GGUF) via `get_llm_langchain()` singleton.

- [x] `ContentValidationResult` gains `requires_ocr: bool` field
- [x] Zero-text detection: if extracted text is empty/whitespace, set `requires_ocr=True` and skip SLM check
- [x] `requires_ocr=True` jobs route to Stage 2 (OCR pipeline) instead of being rejected
- [x] `config/content_validation.yaml` has `min_chars` and `allowed_languages`
- [x] `passed=False` for text shorter than `MIN_CHARS` (non-OCR path)
- [x] `passed=False, needs_agent_review=True` for non-Spanish text
- [x] `passed=True` for valid Spanish text sample
- [x] `LegitimacyDecision(BaseModel)` matches spec schema
- [x] `_slm_legitimacy_check()` calls `build_content_chain(llm)` → parsed result
- [x] Emits events + records audit on every run (including `requires_ocr` branch)
- [x] Tests cover all paths using `MockLlm`, including image-only PDF branch
- [x] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_node3.py
```

---

### T14 · Node 4 — Duplicate Control
**Branch:** `feat/node4-duplicate-control` · **Deps:** T03 · T07 · T08 · **Status:** `[x]` · **PR:** [#4](https://github.com/leonardoheis/Trabajo-Integrador/pull/4)

- [x] `config/duplicate_control.yaml` has similarity threshold
- [x] SHA-256 match → `is_duplicate=True, duplicate_type="exact", similarity_score=1.0`
- [x] Cosine > threshold → `duplicate_type="semantic"`
- [x] New document → `is_duplicate=False`, hash saved via `IHashRepository`
- [x] `EmbeddingStore` wraps FAISS `IndexFlatIP` with injectable `EmbedFn` for test isolation
- [x] `IHashRepository` marked `@runtime_checkable` (required by Pydantic field validation)
- [x] `sentence-transformers` model load lazy (`@lru_cache` on `_get_sentence_model()`)
- [x] Tests use `InMemoryHashRepository` + 4-dim FAISS index with stub embed functions (7 tests)
- [x] Playground notebook: `playground/node4_duplicate_control.ipynb`
- [x] `uv run poe check` passes (182 tests)

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_node4.py
```

---

### T15 · Coordinator — LangGraph state machine
**Branch:** `feat/coordinator` · **Deps:** T09 · T12 · T13 · T14 · **Status:** `[x]`

- [x] `JobState` TypedDict with all required fields
- [x] LangGraph: node1 → node2 → node3 → node4, conditional edges to `accept`/`reject`/`review`
- [x] `_accept`, `_reject`, `_review` terminal nodes set `final_status` + `rejection_reason`
- [x] Integration test: valid PDF → all 4 nodes → `accepted`
- [x] Integration test: empty file → rejected at node 1
- [x] Integration test: image-only PDF → routes to OCR (node3 sets `requires_ocr`)
- [x] Integration test: non-legitimate content → `review`
- [x] Integration test: duplicate PDF → rejected at node4
- [x] Uses `MockLlm` + `InMemory*`; no real model or DB
- [x] `uv run poe check` passes (188 tests)

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_coordinator.py
```

---

### T16 · FastAPI app + health route
**Branch:** `feat/fastapi-app` · **Deps:** T01 · **Status:** `[x]` · **PR:** pending

- [x] `dependency-injector>=4.41` in `pyproject.toml`
- [x] `injections/__init__.py`: `configure_container()` with `@cache`
- [x] `injections/production.py`: `Container` with `providers.Resource(get_session)`, `providers.Factory` for all `Sql*` repos, `AuditService`, `providers.Singleton(EventBroadcaster)`
- [x] `injections/test.py`: `TestContainer` with all `InMemory*` repos, `AuditService`, `EventBroadcaster`
- [x] `api/app.py`: `create_app()` calls `configure_container()`, mounts all routers and error handlers
- [x] `GET /health` → `{"status": "healthy", "message": "..."}`, HTTP 200, public
- [x] `api/schemas.py`: `BaseSchema` with camel-case aliases
- [x] `tests/api/conftest.py`: `client` fixture (TestContainer wired) + `auth_headers` fixture
- [x] `tests/api/routes/test_health.py`: asserts health response shape and status 200
- [x] `uv run poe check` passes (189 tests)

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
- [ ] `GET /pipeline/{job_id}/events` streams `node_started`/`node_passed`/`node_failed` per node
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

### T20 · wandb integration — LLM tracing + per-node metrics
**Branch:** `feat/wandb` · **Deps:** T11 · T09–T14 · **Status:** `[ ]`

**Strategy A — LangChain callback (zero node changes):**
- [ ] `wandb>=0.17` added to `pyproject.toml`; `uv sync --dev` succeeds
- [ ] `ingesta/llm_provider.py`: `get_llm_langchain()` accepts optional `callbacks` list; production default is `[WandbCallbackHandler(project="classiflow")]` when `WANDB_API_KEY` is set
- [ ] `settings.py` has `WANDB_API_KEY: str = ""` and `WANDB_PROJECT: str = "classiflow"`
- [ ] Every LLM call (nodes 2 & 3) logs: prompt text, raw output, latency, token count
- [ ] `WANDB_API_KEY` unset → callbacks list is empty, no wandb import side-effects

**Strategy B — per-node `wandb.log()` (richer metrics):**
- [ ] Each node's `run()` calls `wandb.log({"node": self.name, "duration_ms": duration_ms, "passed": result.passed})` after audit
- [ ] Node 3 logs additionally: `confidence`, `detected_language`
- [ ] Node 4 logs additionally: `is_duplicate`, `duplicate_type`, `similarity_score`
- [ ] Guarded by `if settings.WANDB_API_KEY` — no wandb traffic in tests

**Tests:**
- [ ] Strategy A: test that `WandbCallbackHandler` is in the callbacks list when `WANDB_API_KEY` is set
- [ ] Strategy B: test that `wandb.log` is called with expected keys (mock `wandb.log`)
- [ ] All existing tests unchanged (wandb disabled when `WANDB_API_KEY` is empty)
- [ ] `uv run poe check` passes

```bash
# Verify
WANDB_API_KEY=your_key uv run python -c "
from classiflow.ingesta.llm_provider import get_llm_langchain
from classiflow.settings import Settings
llm = get_llm_langchain(Settings.node3_model_path)
print(llm.callbacks)
"
```

---

### T21 · Text extraction — MarkItDown + PaddleOCR fallback
**Branch:** `feat/text-extraction` · **Deps:** T15 · **Status:** `[ ]`

Add a real `text_extractor` to the coordinator that tries MarkItDown first and falls back to PaddleOCR for image-heavy PDFs, replacing the current UTF-8 decode stub.

**Dependencies to add (`pyproject.toml`):**
- [ ] `markitdown[pdf]>=0.1` (text extraction from PDF/DOCX/XLSX)
- [ ] `paddlepaddle>=2.6` + `paddleocr>=2.8` (OCR engine)

**New file `src/classiflow/ingesta/extract.py`:**
- [ ] `MIN_TEXT_FOR_OCR: int = 50` — if MarkItDown yields fewer chars, fall back to OCR
- [ ] `MIN_USABLE_TEXT: int = 20` — if still below after OCR, return `""` (Node 3 rejects as image-only)
- [ ] `extract_document(file_bytes: bytes, filename: str) -> str` — public entry point
  - Writes bytes to a temp file (MarkItDown requires a path)
  - Tries `MarkItDown().convert(path).text_content`
  - If `len(text) < MIN_TEXT_FOR_OCR`: initializes `PaddleOCR(lang="es")` and runs on each page rendered via `fitz` at 200 dpi
  - Returns cleaned, stripped text (or `""` on total failure)
- [ ] `_get_ocr() -> PaddleOCR` — `@lru_cache(maxsize=1)` singleton (same pattern as `_get_detector`)

**Coordinator wiring (`src/classiflow/ingesta/coordinator.py`):**
- [ ] Default `text_extractor` changed from UTF-8 stub to `extract_document`

**Tests (`tests/ingesta/test_extract.py`):**
- [ ] `test_markitdown_sufficient_text` — mock MarkItDown returning ≥ 50 chars; OCR not called
- [ ] `test_ocr_fallback_when_text_thin` — mock MarkItDown returning < 50 chars; OCR mock called
- [ ] `test_both_fail_returns_empty` — both raise; result is `""`
- [ ] `uv run poe check` passes

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
| T09 | Node 1 — File Reception | `[x]` done — PR [#13](https://github.com/lgj2911/Trabajo-Integrador/pull/13) |
| T10 | Node 2 — Format Validation (rule-based) | `[x]` done — PR [#15](https://github.com/lgj2911/Trabajo-Integrador/pull/15) |
| T11 | LLM Provider singleton | `[x]` done — PR [#17](https://github.com/lgj2911/Trabajo-Integrador/pull/17) [#18](https://github.com/lgj2911/Trabajo-Integrador/pull/18) |
| T12 | Node 2 — SLM escalation path | `[x]` done — PR [#19](https://github.com/leonardoheis/Trabajo-Integrador/pull/19) |
| T13 | Node 3 — Content Validation | `[x]` done — PR [#1](https://github.com/leonardoheis/Trabajo-Integrador/pull/1) |
| T14 | Node 4 — Duplicate Control | `[x]` done — PR [#4](https://github.com/leonardoheis/Trabajo-Integrador/pull/4) |
| T15 | Coordinator — LangGraph | `[x]` done |
| T16 | FastAPI app + health route | `[x]` done — PR pending |
| T17 | Pipeline endpoints + SSE stream | `[ ]` pending |
| T18 | GitHub Actions CI | `[-]` skipped for now |
| T19 | Docker build + push | `[ ]` pending |
| T20 | wandb integration — LLM tracing + per-node metrics | `[ ]` pending |
| T21 | Text extraction — MarkItDown + PaddleOCR fallback | `[ ]` pending |

**14 / 21 tasks complete · 1 skipped (T18)**

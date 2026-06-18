# Implementation Plan: Classiflow — Ingesta Stage + API Layer

## Project Context

Classiflow is a multi-stage document classification system for Municipalidad de Rosario.
This plan covers **Stage 1: Ingesta** and the **API + Auth + Database + CI/CD infrastructure**
that supports it. The frontend is a future deliverable and is not planned here.

### Full pipeline (conceptual — stages beyond Ingesta are out of scope here)

```
Sources
  ├── Municipal dataset (PDF documents — already available, no scraping needed now)
  └── Manual upload via API (PDF · DOCX · img)
          │
          ▼
┌─────────────────────────────────────────────────────┐
│  Stage 1: Ingesta          ◄── THIS PLAN            │
│  File reception · Format validation ·               │
│  Content validation · Duplicate control             │
└─────────────────────────────────────────────────────┘
          │ accepted files only
          ▼
┌─────────────────────────────────────────────────────┐
│  Stage 2: Text Extraction  [future]                 │
│  Text · Page images · Document structure            │
└─────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────┐
│  Stage 3: Refinement & Enrichment  [future]         │
│  Quality checks · Cleanup · Metadata tagging        │
└─────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────┐
│  Stage 4: Orchestrator  [future]                    │
│  ├── Ingestion agent  (receive · validate · detect language)
│  ├── Classification agent  (document type · confidence score)
│  ├── Confidence gate  (auto · review · escalation)  │
│  └── Routing agent  (directory · audit log)         │
└─────────────────────────────────────────────────────┘
          │
          ├── Knowledge Base (chunks · vectors · sources)  [future]
          │         └── Chat Agent (query · retrieve · respond with sources)
          │
          └── Outputs
                ├── Classified documents
                ├── Review queue  (low confidence)
                └── Audit log  (every decision, every stage)

Web Interface: upload · agent visualization · classification · chat  [future]
```

---

## Ingesta Stage: Responsibility

The Ingesta stage is the **first and only processing gate** before content enters the system.
Its job is to determine whether a file is **safe, valid, and new** — it never reads document
content deeply. Accepted files are handed off to Stage 2.

The stage is a sequential 4-agent chain coordinated by a LangGraph state machine, triggered
exclusively by the API. There is no filesystem watcher in scope.

---

## How the API Fits

The pipeline is **API-first and protected by JWT auth**. A logged-in user uploads a document
via `POST /pipeline/ingest`. The API creates a `job_id`, starts the coordinator as an async
background task, and immediately returns. The client then opens
`GET /pipeline/{job_id}/events` (Server-Sent Events) to receive real-time agent state updates.

```
Client                       API (FastAPI)                Background Task
  │                               │                              │
  │── POST /auth/login ──────────►│── redirect → Google OAuth    │
  │◄── 302 → accounts.google.com ─│                              │
  │── GET /auth/callback?code=X ─►│── verify · check whitelist   │
  │◄── { access_token: "JWT" } ───│── issue JWT                  │
  │                               │                              │
  │── POST /pipeline/ingest ──────│  (Authorization: Bearer JWT) │
  │   (file upload)               │                              │
  │◄── 202 { job_id: "abc-123" } ─│── create_task() ────────────►│
  │                               │                              │
  │── GET /pipeline/abc-123/events│                              │
  │   (SSE stream open)           │   Agent 1 starts             │
  │◄── event: agent_started ──────│◄── emit() ──────────────────│
  │◄── event: agent_passed ───────│◄── emit() ──────────────────│
  │◄── event: agent_started ──────│◄── emit() (Agent 2) ─────────│
  │          ...                  │                              │
  │◄── event: pipeline_done ──────│◄── emit() ──────────────────│
  │    (SSE stream closes)         │                              │
```

---

## Architecture Decisions

### API & Transport
- **FastAPI** — async, OpenAPI docs, native SSE via `StreamingResponse`.
- **SSE over WebSocket** — pipeline events are unidirectional server→client; SSE is simpler
  and works over plain HTTP without a protocol upgrade.
- **`asyncio.Queue` per job** — in-memory event broadcaster. Swap to Redis pub/sub later
  without touching any agent code.

### Auth
- **Google OAuth 2.0** (`authlib`) — users sign in with Gmail; no password management.
- **JWT** (`python-jose`) — issued after the OAuth callback, verified on every protected route
  via a FastAPI dependency. Scope: access restriction only (no roles, no RBAC for now).
- **Whitelist/blacklist in the DB** — `AllowedUser` table controls who can log in.
  Blacklist is a flag on the same row. Managed via a seed script or future admin route.

### Database & Persistence
- **SQLAlchemy 2.0 (async)** + **aiosqlite** — SQLite for local development.
- **Switch to PostgreSQL for production**: change one connection string + swap `aiosqlite`
  driver for `asyncpg`. Zero code changes elsewhere.
- **Repository pattern** (Protocol-based interfaces) — services depend on repository
  protocols, not on SQLAlchemy sessions directly. This is the abstraction layer that
  survives a database migration.
- **Alembic** for schema migrations — applies cleanly on both SQLite and PostgreSQL.

### Domain Classes
- **No `@dataclass`** — all value objects and domain models use `class` with Pydantic
  `BaseModel`. This gives validation, JSON serialization, and type-safe field access
  without the limitations of frozen dataclasses.
- **ORM models** (SQLAlchemy `DeclarativeBase`) are separate from domain models. The
  repository maps between them.

### LLM / Agents
- **`llama-cpp-python` over Ollama** — embedded in-process, no HTTP round-trip, native
  grammar-constrained JSON output, easy to mock in tests.
- **Shared LLM singleton** (`@lru_cache`) — loaded once at startup, injected into Agent 2
  and Agent 3. Avoids reloading 2.5 GB per job.
- **LangChain for Agent 2 and Agent 3 only** — `PromptTemplate` + `JsonOutputParser`
  allow model swaps without touching agent logic.
- **LangGraph as Coordinator** — typed state graph with conditional edges.

### Cross-Platform & Deployment
- **Target OS: Linux** (Ubuntu/Debian). Docker image uses `python:3.12-slim` (Linux).
- **`python-magic`** (not `python-magic-bin`) — the `python-magic` package works on Linux
  with `libmagic1` installed (`apt-get install libmagic1`). On Windows dev machines,
  install `python-magic-bin` manually (not in `pyproject.toml`).
- **Config in `config/`** at project root — editable without reinstalling the package.

### Dependency Injection
- **`dependency-injector`** (`DeclarativeContainer` + `@inject` + `Provide`) — explicit container
  that wires all services and repositories. Endpoint functions declare typed aliases in
  `api/dependencies.py`; no manual object construction inside routes.
- **`Container`** (production) wires `Sql*` repositories to the async DB session.
- **`TestContainer`** overrides every `Sql*` provider with its `InMemory*` variant — tests get
  full service logic with zero DB or network setup, no mocking.
- **`configure_container()`** called once at application startup (`@lru_cache` ensures a single
  instance per process); wired to `api.routes` package so `@inject` resolves automatically.

### CI/CD
- **GitHub Actions** — lint → typecheck → test → Docker build on every push.
- Coverage gate: fail if below 80%.
- Docker image pushed to registry only on push to `main`.

---

## Repository Pattern (SOLID reference)

Every resource that touches the database has three classes:

```python
# 1. Protocol — the interface services depend on (Dependency Inversion Principle)
class IHashRepository(Protocol):
    def exists(self, sha256: str) -> bool: ...
    def save(self, sha256: str, job_id: str) -> None: ...

# 2. SQLAlchemy implementation — swappable without touching callers
class SqlHashRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, sha256: str) -> bool:
        result = await self._session.execute(
            select(HashRecord).where(HashRecord.sha256 == sha256)
        )
        return result.scalar_one_or_none() is not None

# 3. In-memory implementation — used in unit tests only
class InMemoryHashRepository:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def exists(self, sha256: str) -> bool:
        return sha256 in self._store
```

Agents and services receive the protocol type as a constructor parameter.
Tests inject `InMemory*` instances via `TestContainer`. Production injects `Sql*` instances
via `Container` (dependency-injector `DeclarativeContainer`).

---

## Domain Class Pattern (no @dataclass)

```python
# shared/domain/job.py
class AgentEvent(BaseModel):
    job_id: str
    agent: str        # "agent1_file_reception" | "agent2_format_validation" | ...
    status: JobStatus
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    detail: dict[str, Any] = Field(default_factory=dict)

    def to_sse(self) -> str:
        return f"event: agent_update\ndata: {self.model_dump_json()}\n\n"

class JobStatus(str, Enum):
    STARTED  = "started"
    PASSED   = "passed"
    FAILED   = "failed"
    REJECTED = "rejected"
    REVIEW   = "review"
    DONE     = "done"
```

```python
# ingesta/domain/results.py — domain classes, not dataclasses
class FileReceptionResult(BaseModel):
    passed: bool
    sha256: str = ""
    detected_mime: str = ""
    file_size_bytes: int = 0
    rejection_reason: str = ""

class FormatValidationResult(BaseModel):
    passed: bool
    decision: FormatDecision
    used_slm: bool = False
    rejection_reason: str = ""
```

---

## File Layout (target state)

```
src/classiflow/
├── __init__.py
│
├── api/                                    # FastAPI application
│   ├── __init__.py
│   ├── app.py                              # FastAPI factory + configure_container()
│   ├── dependencies.py                     # Annotated aliases: Depends(Provide[Container.*])
│   ├── schema.py                           # BaseSchema (Pydantic + CamelCase aliases)
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── auth.py                         # JWT verification middleware
│   ├── error_handlers/
│   │   ├── __init__.py
│   │   ├── auth.py                         # AuthError → 401/403
│   │   └── pipeline.py                     # PipelineError → 400/500
│   └── routes/
│       ├── __init__.py
│       ├── health/
│       │   ├── __init__.py
│       │   └── endpoints.py                # GET /health  (public)
│       ├── auth/
│       │   ├── __init__.py
│       │   ├── endpoints.py                # GET /auth/login → OAuth redirect
│       │   │                               # GET /auth/callback → issue JWT
│       │   └── schemas.py                  # TokenResponse
│       └── pipeline/
│           ├── __init__.py
│           ├── endpoints.py                # POST /pipeline/ingest  (protected)
│           │                               # GET  /pipeline/{job_id}/events  (protected, SSE)
│           └── schemas.py                  # IngestResponse, AgentEventSchema
│
├── injections/                             # dependency-injector containers
│   ├── __init__.py                         # configure_container() with @lru_cache
│   ├── production.py                       # Container(DeclarativeContainer) — wires Sql* repos + services
│   └── test.py                             # TestContainer — overrides with InMemory* repos
│
├── shared/                                 # Cross-cutting concerns — all stages use these
│   ├── __init__.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── base.py                         # DeclarativeBase, engine factory, get_session()
│   │   ├── models.py                       # ORM models: HashRecord, AuditRecord, AllowedUser
│   │   └── repositories/
│   │       ├── __init__.py
│   │       ├── hash.py                     # IHashRepository (Protocol) + SqlHashRepository
│   │       ├── audit.py                    # IAuditRepository (Protocol) + SqlAuditRepository
│   │       ├── user.py                     # IUserRepository (Protocol) + SqlUserRepository
│   │       ├── document_steps.py           # IDocumentStepsRepository + SqlDocumentStepsRepository
│   │       └── human_decision.py           # IHumanDecisionRepository + SqlHumanDecisionRepository
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── oauth.py                        # Google OAuth flow (authlib)
│   │   └── jwt.py                          # encode_token() / decode_token() (python-jose)
│   ├── audit/
│   │   ├── __init__.py
│   │   └── service.py                      # AuditService — wraps IAuditRepository + loguru
│   ├── events/
│   │   ├── __init__.py
│   │   └── broadcaster.py                  # EventBroadcaster — asyncio.Queue per job_id
│   └── domain/
│       ├── __init__.py
│       ├── job.py                          # AgentEvent, JobStatus (Pydantic BaseModel)
│       └── user.py                         # User, AuthToken (Pydantic BaseModel)
│
└── ingesta/                                # Stage 1 pipeline
    ├── __init__.py
    ├── coordinator.py                      # LangGraph state machine
    ├── llm_provider.py                     # get_llm() / get_llm_langchain() singletons
    ├── domain/
    │   ├── __init__.py
    │   ├── state.py                        # JobState TypedDict (LangGraph)
    │   └── results.py                      # FileReceptionResult, FormatValidationResult,
    │                                       # ContentValidationResult, DuplicateControlResult
    ├── agents/
    │   ├── __init__.py
    │   ├── agent1_file_reception.py
    │   ├── agent2_format_validation.py
    │   ├── agent3_content_validation.py
    │   └── agent4_duplicate_control.py
    └── prompts/
        ├── __init__.py
        ├── format_validation.py
        └── content_validation.py

config/
├── allowed_formats.yaml
├── content_validation.yaml
└── duplicate_control.yaml

alembic/                                    # Database migrations
├── env.py
├── script.py.mako
└── versions/
    └── 0001_initial_schema.py

.github/
└── workflows/
    ├── ci.yml                              # lint · typecheck · test · coverage
    └── docker.yml                          # build + push image (main only)

tests/
├── conftest.py                             # Session-level DI overrides
├── shared/
│   ├── __init__.py
│   └── test_broadcaster.py
├── ingesta/
│   ├── __init__.py
│   ├── conftest.py                         # MockLlm, InMemory repositories, fixture PDFs
│   ├── test_agent1.py
│   ├── test_agent2.py
│   ├── test_agent3.py
│   ├── test_agent4.py
│   └── test_coordinator.py
└── api/
    ├── __init__.py
    ├── conftest.py                         # TestClient, auth bypass fixture
    └── routes/
        ├── test_health.py
        ├── test_auth.py
        └── test_pipeline.py
```

---

## Dependency Graph

```
shared/database/base.py ───────────────────► shared/database/repositories/*
shared/database/repositories/hash.py ──────► agent4_duplicate_control
shared/database/repositories/audit.py ─────► shared/audit/service.py
shared/database/repositories/user.py ──────► shared/auth/oauth.py

shared/auth/jwt.py ─────────────────────────► api/middleware/auth.py
shared/auth/oauth.py ───────────────────────► api/routes/auth/endpoints.py

shared/domain/job.py ───────────────────────► agent1 · agent2 · agent3 · agent4 · coordinator
shared/audit/service.py ────────────────────► agent1 · agent2 · agent3 · agent4 · coordinator
shared/events/broadcaster.py ───────────────► coordinator
                             └──────────────► api/routes/pipeline/endpoints.py (SSE)

config/allowed_formats.yaml ───────────────► agent2_format_validation
config/content_validation.yaml ────────────► agent3_content_validation
config/duplicate_control.yaml ─────────────► agent4_duplicate_control

llm_provider.py ────────────────────────────► agent2_format_validation
               └────────────────────────────► agent3_content_validation

prompts/format_validation.py ──────────────► agent2_format_validation
prompts/content_validation.py ─────────────► agent3_content_validation

agent1 · agent2 · agent3 · agent4 ─────────► coordinator
coordinator ────────────────────────────────► api/routes/pipeline (triggered by background task)
```

---

## Phase 1: Foundation

### Task 1: Package skeleton + dependencies

**Description:** Create the full directory tree with empty `__init__.py` files, stub config
YAMLs, and add all runtime dependencies to `pyproject.toml`.

**Acceptance criteria:**
- [ ] All directories in the target file layout above exist with `__init__.py`
- [ ] `config/` has stub YAMLs for the three configs
- [ ] `alembic/` initialized (`alembic init`)
- [ ] All dependencies added to `pyproject.toml`
- [ ] `uv sync --dev` succeeds and `uv.lock` is updated
- [ ] `uv run poe check` passes (empty modules, no type errors)

**Dependencies:** None

**Dependencies to add to `pyproject.toml`:**
```
# API
fastapi>=0.115
uvicorn[standard]>=0.30
python-multipart>=0.0.9      # multipart file upload
sse-starlette>=2.1           # SSE helper
dependency-injector>=4.41    # DeclarativeContainer + @inject + Provide

# Auth
authlib>=1.3                 # Google OAuth 2.0
python-jose[cryptography]>=3.3  # JWT encode/decode
httpx>=0.27                  # async HTTP for OAuth token exchange

# Database
sqlalchemy>=2.0
aiosqlite>=0.20              # async SQLite driver (swap for asyncpg in production)
alembic>=1.13

# Pipeline
langchain>=0.3
langchain-community>=0.3
langchain-core>=0.3
langgraph>=0.2
loguru>=0.7
python-magic>=0.4            # MIME detection — requires libmagic1 on Linux
                             # On Windows dev: install python-magic-bin manually
lingua-language-detector>=2.0
chardet>=5.0
sentence-transformers>=3.0
faiss-cpu>=1.7
pyyaml>=6.0
```

Note: `llama-cpp-python` must be installed separately (requires CMake + GPU flags).
Document in `INSTALL.md`.

**Files touched:**
- `pyproject.toml`, `uv.lock`
- All `__init__.py` stubs
- `config/allowed_formats.yaml`, `config/content_validation.yaml`, `config/duplicate_control.yaml`
- `alembic/env.py`, `alembic/script.py.mako`

**Estimated scope:** S

### Checkpoint A
- [ ] `uv run poe lint` passes
- [ ] `uv run poe typecheck` passes
- [ ] `python -c "from classiflow.api import app; from classiflow.ingesta import agents"` succeeds

---

## Phase 2: Database Layer

### Task 2: SQLAlchemy base + ORM models + Alembic migration

**Description:** Implement `shared/database/base.py` with the async engine factory and
`get_session()` dependency. Define all ORM models in `shared/database/models.py`.
Write and apply the initial Alembic migration.

**ORM models:**

| Table | Key columns | Purpose |
|---|---|---|
| `allowed_users` | `id`, `email`, `is_active`, `is_blocked`, `created_at` | OAuth whitelist/blacklist |
| `audit_records` | `id`, `job_id`, `agent`, `event`, `timestamp`, `duration_ms`, `detail` (JSON) | Append-only agent execution log |
| `hash_records` | `id`, `sha256`, `job_id`, `ingested_at` | Exact duplicate detection |
| `jobs` | `id`, `job_id`, `status`, `filename`, `created_at`, `updated_at`, `failed_at_agent`, `rejection_reason`, `review_action_needed` | Job tracking + fast review query fields |
| `document_steps` | `id`, `job_id` (FK), `step_order`, `agent`, `status`, `passed`, `rejection_reason`, `duration_ms`, `detail` (JSON), `timestamp` | Ordered per-agent results — full path a document followed |
| `human_decisions` | `id`, `job_id` (FK), `decided_by`, `decision`, `notes`, `decided_at` | Human reviewer actions on flagged documents |

**`jobs` enrichment rationale:** `failed_at_agent`, `rejection_reason`, and `review_action_needed`
are summary fields that allow the review queue to be served from a single table scan without
joining `document_steps`. They are always derived from the agent result that ended the pipeline.

**Acceptance criteria:**
- [ ] `create_async_engine(settings.DATABASE_URL)` works with both `sqlite+aiosqlite://` and `postgresql+asyncpg://`
- [ ] `get_session()` is an async context manager; wired into the container as `providers.Resource`
- [ ] All six ORM models declared with correct types and constraints
- [ ] `jobs` has `failed_at_agent` (VARCHAR nullable), `rejection_reason` (TEXT nullable), `review_action_needed` (VARCHAR nullable)
- [ ] `document_steps` has `step_order`, `agent`, `status`, `passed`, `rejection_reason`, `duration_ms`, `detail` (JSON), `timestamp`; FK → `jobs.job_id`
- [ ] `human_decisions` has `decided_by`, `decision` (`accept`/`reject`/`escalate`), `notes` (TEXT nullable), `decided_at`; FK → `jobs.job_id`
- [ ] `alembic upgrade head` creates all six tables on a fresh SQLite file
- [ ] Changing `DATABASE_URL` to PostgreSQL requires no code changes (only config)
- [ ] `uv run poe typecheck` passes

**Dependencies:** Task 1

**Files touched:**
- `src/classiflow/shared/database/base.py`
- `src/classiflow/shared/database/models.py`
- `alembic/versions/0001_initial_schema.py`
- `src/classiflow/settings.py`  (add `DATABASE_URL`)

**Estimated scope:** M

### Task 3: Repository implementations

**Description:** Implement the four Protocol interfaces and their SQLAlchemy-backed
implementations. Also implement the `InMemory*` variants used only by tests.

**Acceptance criteria:**
- [ ] `IHashRepository`, `IAuditRepository`, `IUserRepository`, `IHumanDecisionRepository` are `Protocol` classes
- [ ] `SqlHashRepository`, `SqlAuditRepository`, `SqlUserRepository`, `SqlHumanDecisionRepository` implement them via SQLAlchemy
- [ ] `InMemoryHashRepository`, `InMemoryAuditRepository`, `InMemoryUserRepository`, `InMemoryHumanDecisionRepository` implement them in-memory
- [ ] `IDocumentStepsRepository` protocol with `save_step()` and `steps_for_job()` methods
- [ ] `SqlDocumentStepsRepository` + `InMemoryDocumentStepsRepository` implementations
- [ ] mypy verifies each concrete class satisfies its protocol (structural check)
- [ ] Unit tests cover each concrete implementation (SQL via in-memory SQLite, not mocks)

**Dependencies:** Task 2

**Files touched:**
- `src/classiflow/shared/database/repositories/hash.py`
- `src/classiflow/shared/database/repositories/audit.py`
- `src/classiflow/shared/database/repositories/user.py`
- `src/classiflow/shared/database/repositories/document_steps.py`
- `src/classiflow/shared/database/repositories/human_decision.py`
- `tests/shared/test_repositories.py`

**Estimated scope:** M

### Checkpoint B
- [ ] `uv run poe check` passes
- [ ] `alembic upgrade head` creates all tables
- [ ] Repository round-trip tests pass against in-memory SQLite

---

## Phase 3: Auth

### Task 4: JWT utilities

**Description:** Implement `shared/auth/jwt.py` with `encode_token(user_email)` and
`decode_token(token)`. Tokens carry `sub` (email), `exp`, and `iat`. Signing key and
expiry come from `settings`.

**Acceptance criteria:**
- [ ] `encode_token` returns a signed JWT string
- [ ] `decode_token` returns the payload dict or raises `AuthError` on invalid/expired token
- [ ] Expiry is configurable via `settings.JWT_EXPIRE_MINUTES`
- [ ] Unit tests cover valid token, expired token, tampered signature
- [ ] No secrets hardcoded; key read from `settings.JWT_SECRET_KEY` (env var)

**Dependencies:** Task 1

**Files touched:**
- `src/classiflow/shared/auth/jwt.py`
- `src/classiflow/settings.py`  (add `JWT_SECRET_KEY`, `JWT_EXPIRE_MINUTES`)
- `tests/api/test_auth.py`

**Estimated scope:** S

### Task 5: Google OAuth flow + whitelist check

**Description:** Implement `shared/auth/oauth.py` with two functions:
`get_authorization_url()` (returns the Google redirect URL) and
`exchange_code(code)` (exchanges the OAuth code for a Google user profile, checks
`IUserRepository`, issues a JWT). Implement `api/routes/auth/endpoints.py`.

**Acceptance criteria:**
- [ ] `GET /auth/login` redirects to Google with correct `scope=email profile`
- [ ] `GET /auth/callback?code=X` exchanges the code, verifies the email against `allowed_users`
- [ ] Returns HTTP 403 if the email is not in the whitelist or is blocked
- [ ] Returns `TokenResponse(access_token=<JWT>, token_type="bearer")` on success
- [ ] OAuth flow is tested using `httpx.MockTransport` (no real Google call in tests)
- [ ] `IUserRepository` is injected — tests use `InMemoryUserRepository`

**Dependencies:** Tasks 3, 4

**Files touched:**
- `src/classiflow/shared/auth/oauth.py`
- `src/classiflow/api/routes/auth/endpoints.py`
- `src/classiflow/api/routes/auth/schemas.py`
- `src/classiflow/api/error_handlers/auth.py`
- `tests/api/routes/test_auth.py`

**Estimated scope:** M

### Task 6: JWT middleware

**Description:** Implement `api/middleware/auth.py` as a FastAPI dependency (not Starlette
middleware) so it can be applied per-router. Protected routes declare
`CurrentUser = Annotated[User, Depends(Provide[Container.current_user])]` and decorate
endpoint functions with `@inject`.

**Acceptance criteria:**
- [ ] `require_auth` extracts the `Authorization: Bearer <token>` header
- [ ] Returns HTTP 401 if header is missing or token is invalid
- [ ] Returns the decoded `User` domain object on success
- [ ] `/health` and `/auth/*` routes are explicitly public (no `require_auth` dependency)
- [ ] `CurrentUser` alias uses `Provide[Container.current_user]`; endpoint uses `@inject`
- [ ] Tests verify 401 on missing token, 401 on expired token, 200 on valid token

**Dependencies:** Tasks 4, 5

**Files touched:**
- `src/classiflow/api/middleware/auth.py`
- `src/classiflow/api/dependencies.py`
- `tests/api/conftest.py`  (add `auth_headers` fixture)

**Estimated scope:** S

### Checkpoint C
- [ ] `uv run poe check` passes
- [ ] Auth flow tests pass (no real Google calls)
- [ ] Protected route rejects unauthenticated requests

---

## Phase 4: Shared Infrastructure

### Task 7: Domain types + AuditService + EventBroadcaster

**Description:** Implement the shared building blocks that every pipeline module depends on.

- `shared/domain/job.py`: `AgentEvent` and `JobStatus` as Pydantic `BaseModel` classes.
- `shared/domain/user.py`: `User` and `AuthToken` as Pydantic `BaseModel` classes.
- `shared/audit/service.py`: `AuditService` wraps `IAuditRepository` and writes a loguru
  line per entry (structured JSON). Agents call `AuditService`, not the repository directly.
- `shared/events/broadcaster.py`: `EventBroadcaster` with one `asyncio.Queue` per `job_id`.

**Acceptance criteria:**
- [ ] `AgentEvent` is a `BaseModel` with a `to_sse()` method returning the SSE wire format
- [ ] `JobStatus` is a `str` enum
- [ ] `AuditService.record(event)` persists to DB via `IAuditRepository` and writes a loguru line
- [ ] `EventBroadcaster.emit(event)` puts the event on the correct queue
- [ ] `EventBroadcaster.subscribe(job_id)` returns an async generator; closes cleanly on `DONE`
- [ ] `EventBroadcaster.close(job_id)` removes the queue (called in `finally` on SSE disconnect)
- [ ] Unit tests cover emit→subscribe round-trip, early disconnect cleanup, and `AuditService`
- [ ] No `@dataclass` anywhere in this task

**Dependencies:** Tasks 2, 3

**Files touched:**
- `src/classiflow/shared/domain/job.py`
- `src/classiflow/shared/domain/user.py`
- `src/classiflow/shared/audit/service.py`
- `src/classiflow/shared/events/broadcaster.py`
- `tests/shared/test_broadcaster.py`
- `tests/shared/test_audit_service.py`

**Estimated scope:** S

### Checkpoint D
- [ ] `uv run poe check` passes
- [ ] Broadcaster round-trip and audit persistence tests pass

---

## Phase 5: Deterministic Agents (no LLM)

### Task 8: Ingesta domain models

**Description:** Define all result models in `ingesta/domain/results.py` and `JobState`
in `ingesta/domain/state.py`. Pure typed data — no logic, no IO.

**Acceptance criteria:**
- [ ] `FileReceptionResult`, `FormatValidationResult`, `ContentValidationResult`,
  `DuplicateControlResult` are Pydantic `BaseModel` classes (not dataclasses)
- [ ] `JobState` is a `TypedDict` with all fields consumed by the LangGraph coordinator
- [ ] mypy strict passes; no `Any` usage

**Dependencies:** Task 1

**Files touched:**
- `src/classiflow/ingesta/domain/results.py`
- `src/classiflow/ingesta/domain/state.py`

**Estimated scope:** S

### Task 9: Config YAMLs + Agent 1 — File Reception

**Description:** Fill stub config YAMLs. Implement `agent1_file_reception.py` — the
deterministic first gate. Checks file existence, size bounds, computes SHA-256, detects
MIME from `python-magic`. Emits SSE events and persists an audit record.

**Acceptance criteria:**
- [ ] `config/allowed_formats.yaml` has entries for pdf, docx, image (html disabled)
- [ ] Returns `FileReceptionResult(passed=False)` for: missing file, empty file, size > limit
- [ ] Returns `FileReceptionResult(passed=True)` with correct `sha256` and `detected_mime` for a valid PDF
- [ ] Emits `agent_started` then `agent_passed`/`agent_failed` via `EventBroadcaster`
- [ ] Calls `AuditService.record()` with duration and detail on every execution
- [ ] Agent constructor: `__init__(self, audit: AuditService, broadcaster: EventBroadcaster)`
- [ ] mypy strict passes
- [ ] `test_agent1.py` covers all code paths using `InMemory*` dependencies

**Dependencies:** Tasks 7, 8

**Files touched:**
- `config/allowed_formats.yaml`
- `src/classiflow/ingesta/agents/agent1_file_reception.py`
- `tests/ingesta/test_agent1.py`

**Estimated scope:** S

### Task 10: Agent 2 — Format Validation (rule-based path)

**Description:** Implement the rule-based path of `agent2_format_validation.py`. The SLM
escalation stub raises `NotImplementedError` until Task 12.

**Acceptance criteria:**
- [ ] `_rule_based_check()` returns `ACCEPT` for `.pdf` with magic bytes `%PDF`
- [ ] `_rule_based_check()` returns `REJECT` for `.html` (disabled in config)
- [ ] `_rule_based_check()` returns `MANUAL_REVIEW` for unknown MIME
- [ ] `_rule_based_check()` returns `None` (gray zone) for MIME/extension mismatch
- [ ] Emits events + records audit on every execution
- [ ] Unit tests cover all four branches

**Dependencies:** Tasks 7, 8, 9

**Files touched:**
- `src/classiflow/ingesta/agents/agent2_format_validation.py`
- `tests/ingesta/test_agent2.py`

**Estimated scope:** M

### Checkpoint E
- [ ] `uv run poe check` passes
- [ ] Agents 1 and 2 rule-based tests pass

---

## Phase 6: LLM Integration

### Task 11: LLM Provider singleton

**Description:** Implement `llm_provider.py` with `get_llm()` and `get_llm_langchain()`,
both `@lru_cache(maxsize=1)`. Add `MockLlm` for tests.

**Acceptance criteria:**
- [ ] Both functions are type-annotated and return the correct types
- [ ] Calling `get_llm()` twice returns the same instance
- [ ] `MockLlm` substitutes wherever `Llama` is expected; returns a fixed JSON string
- [ ] `llama_cpp` import guarded: `TYPE_CHECKING` + runtime `try/except` with a clear error
- [ ] mypy passes

**Dependencies:** Task 1

**Files touched:**
- `src/classiflow/ingesta/llm_provider.py`
- `tests/ingesta/conftest.py`  (expose `MockLlm` fixture)

**Estimated scope:** S

### Task 12: Agent 2 — SLM escalation path + prompts

**Description:** Fill `prompts/format_validation.py`. Wire `_slm_check()` in Agent 2,
replacing the `NotImplementedError` stub.

**Acceptance criteria:**
- [ ] `FormatDecision` is a Pydantic `BaseModel` matching the spec schema
- [ ] `build_format_chain(llm)` returns a LangChain LCEL chain
- [ ] `_slm_check()` invokes the chain and returns `FormatValidationResult(used_slm=True)`
- [ ] Gray-zone input end-to-end: calls `_slm_check()` → emits event → records audit
- [ ] Tests use `MockLlm`; no real model required

**Dependencies:** Tasks 10, 11

**Files touched:**
- `src/classiflow/ingesta/prompts/format_validation.py`
- `src/classiflow/ingesta/agents/agent2_format_validation.py`
- `tests/ingesta/test_agent2.py`

**Estimated scope:** M

### Task 13: Agent 3 — Content Validation

**Description:** Implement `agent3_content_validation.py` with rule-based checks (language
detection via `lingua`, encoding via `chardet`, min char count) and SLM escalation.

**Acceptance criteria:**
- [ ] Returns `passed=False` for text shorter than `MIN_CHARS`
- [ ] Returns `passed=False, needs_agent_review=True` for non-Spanish text
- [ ] Returns `passed=True` for a valid Spanish text sample
- [ ] `LegitimacyDecision` is a Pydantic `BaseModel`
- [ ] `_slm_legitimacy_check()` calls `build_content_chain(llm)` and returns parsed result
- [ ] Emits events + records audit on every execution
- [ ] Tests cover all paths using `MockLlm`

**Dependencies:** Tasks 7, 8, 11

**Files touched:**
- `config/content_validation.yaml`
- `src/classiflow/ingesta/prompts/content_validation.py`
- `src/classiflow/ingesta/agents/agent3_content_validation.py`
- `tests/ingesta/test_agent3.py`

**Estimated scope:** M

### Checkpoint F
- [ ] `uv run poe check` passes
- [ ] Agents 1–3 callable end-to-end with `MockLlm`

---

## Phase 7: Duplicate Control

### Task 14: Agent 4 — Duplicate Control

**Description:** Implement `agent4_duplicate_control.py` with two-layer detection: exact
SHA-256 via `IHashRepository`, and semantic near-duplicate via `sentence-transformers` + FAISS.

**Acceptance criteria:**
- [ ] Layer 1: SHA-256 match → `DuplicateControlResult(is_duplicate=True, duplicate_type="exact")`
- [ ] Layer 2: cosine similarity > threshold → `duplicate_type="semantic"`
- [ ] New document → `is_duplicate=False`, hash saved via `IHashRepository`
- [ ] Constructor: `__init__(self, hash_repo: IHashRepository, audit: AuditService, broadcaster: EventBroadcaster)`
- [ ] Tests use `InMemoryHashRepository`; no DB required
- [ ] `sentence-transformers` model load is lazy (not at import time)
- [ ] Emits events + records audit on every execution

**Dependencies:** Tasks 3, 7, 8

**Files touched:**
- `config/duplicate_control.yaml`
- `src/classiflow/ingesta/agents/agent4_duplicate_control.py`
- `tests/ingesta/test_agent4.py`

**Estimated scope:** M

### Checkpoint G
- [ ] `uv run poe check` passes
- [ ] All four agent tests pass

---

## Phase 8: Orchestration

### Task 15: Coordinator — LangGraph state machine

**Description:** Implement `coordinator.py`. Defines `JobState`, one graph node per agent,
and conditional edges. Injects all dependencies at construction. Terminal states write to
`AuditService` and emit `pipeline_done`.

```
              ┌────────────────────────────────────────────────────┐
job_start ───►│ agent1 ──► agent2 ──► agent3 ──► agent4          │
              │    │           │           │           │           │
              │  reject    reject/     review/     duplicate/new   │
              │            review      reject                      │
              └──────┬──────────┬──────────┬──────────┬───────────┘
                     ▼          ▼          ▼          ▼
                  rejected   review     review     accepted
                     └──────────┴──────────┴──────────┘
                                       │
                             emit pipeline_done (all paths)
```

**Acceptance criteria:**
- [ ] `JobState` TypedDict has all required fields
- [ ] Graph edges match the routing diagram above
- [ ] `handle_accept`, `handle_reject`, `handle_review` each call `AuditService.record_routing()`
- [ ] `pipeline_done` event emitted on every terminal state
- [ ] End-to-end integration test: valid PDF → all 4 agents pass → `accepted`
- [ ] End-to-end test: empty file → rejected at agent 1 → `rejected`
- [ ] Uses `MockLlm` and `InMemory*` repos; no real model or DB required

**Dependencies:** Tasks 9, 12, 13, 14

**Files touched:**
- `src/classiflow/ingesta/coordinator.py`
- `tests/ingesta/test_coordinator.py`

**Estimated scope:** L

---

## Phase 9: API Layer

### Task 16: FastAPI application + health route

**Description:** Implement `api/app.py` (factory function), `api/schema.py` (BaseSchema),
error handlers, `routes/health/endpoints.py`, and the dependency-injector containers.

**Acceptance criteria:**
- [ ] `create_app()` returns a `FastAPI` instance with all routers and error handlers mounted
- [ ] `create_app()` calls `configure_container()` to wire the `Container` to `api.routes`
- [ ] `GET /health` returns `{"status": "ok"}` and HTTP 200 (public, no auth)
- [ ] `BaseSchema` uses `alias_generator=to_camel`, `populate_by_name=True`
- [ ] `injections/production.py`: `Container(DeclarativeContainer)` wires `Sql*` repos + `AuditService` + `EventBroadcaster`
- [ ] `injections/test.py`: `TestContainer` overrides every `Sql*` provider with `InMemory*`
- [ ] `tests/api/conftest.py` uses `TestContainer`; `@inject` resolves without real DB
- [ ] `dependency-injector>=4.41` added to `pyproject.toml`
- [ ] Tests pass with `TestClient`

**Dependencies:** Task 1

**Files touched:**
- `src/classiflow/api/app.py`
- `src/classiflow/api/schema.py`
- `src/classiflow/api/error_handlers/__init__.py`
- `src/classiflow/api/routes/health/endpoints.py`
- `src/classiflow/injections/__init__.py`
- `src/classiflow/injections/production.py`
- `src/classiflow/injections/test.py`
- `pyproject.toml`  (add `dependency-injector>=4.41`)
- `tests/api/conftest.py`
- `tests/api/routes/test_health.py`

**Estimated scope:** S

### Task 17: Pipeline endpoints + SSE stream

**Description:** Implement `POST /pipeline/ingest`, `GET /pipeline/{job_id}/events`,
`GET /pipeline/review-queue`, and `POST /pipeline/{job_id}/decision`.
All routes are protected by `require_auth`.

- `POST /pipeline/ingest` — accepts multipart file upload, generates `job_id`, starts
  coordinator as an `asyncio` background task, returns HTTP 202 immediately.
- `GET /pipeline/{job_id}/events` — subscribes to `EventBroadcaster`, streams each
  `AgentEvent` as SSE until `pipeline_done` or client disconnect.
- `GET /pipeline/review-queue` — returns all jobs with `status = REVIEW`, each including
  the ordered `document_steps` and the agent that flagged it, so a reviewer has full context.
- `POST /pipeline/{job_id}/decision` — records a human decision (`accept`/`reject`/`escalate`)
  via `IHumanDecisionRepository`; updates `jobs.status` accordingly.

**Acceptance criteria:**
- [ ] `POST /pipeline/ingest` returns HTTP 202 with `job_id` within 100 ms
- [ ] SSE stream delivers `agent_started` + `agent_passed`/`agent_failed` per agent
- [ ] SSE stream closes cleanly on `pipeline_done`
- [ ] Client disconnect before completion removes the queue (`try/finally` in generator)
- [ ] Returns HTTP 404 for unknown `job_id`
- [ ] Returns HTTP 401 without valid JWT
- [ ] `GET /pipeline/review-queue` returns only jobs with `status = REVIEW`, each with `document_steps` inline
- [ ] `POST /pipeline/{job_id}/decision` accepts `decision: accept | reject | escalate` + optional `notes`; persists via `IHumanDecisionRepository`; updates `jobs.status`
- [ ] `POST /pipeline/{job_id}/decision` returns HTTP 404 for unknown job, HTTP 409 if job is not in `REVIEW` state
- [ ] Tests assert the full SSE event sequence using `MockLlm` + small PDF fixture
- [ ] Tests assert review queue contents and decision recording using `InMemory*` repos

**Dependencies:** Tasks 6, 7, 15, 16

**Files touched:**
- `src/classiflow/api/routes/pipeline/endpoints.py`
- `src/classiflow/api/routes/pipeline/schemas.py`  (add `ReviewQueueItem`, `DecisionRequest`)
- `src/classiflow/api/dependencies.py`
- `tests/api/routes/test_pipeline.py`

**Estimated scope:** L

### Checkpoint H — Final
- [ ] `uv run poe check` passes (lint + typecheck + nbtest)
- [ ] `uv run poe test` — all tests green, coverage ≥ 80%
- [ ] Manual smoke test:
  ```bash
  uv run uvicorn classiflow.api.app:create_app --factory --reload
  # 1. Obtain JWT (from /auth/callback after Google login)
  # 2. Upload file
  curl -X POST http://localhost:8000/pipeline/ingest \
       -H "Authorization: Bearer <JWT>" \
       -F "file=@tests/fixtures/sample.pdf"
  # 3. Stream events
  curl -N http://localhost:8000/pipeline/<job_id>/events \
       -H "Authorization: Bearer <JWT>"
  ```

---

## Phase 10: CI/CD

### Task 18: GitHub Actions — CI pipeline

**Description:** Implement `.github/workflows/ci.yml`. Runs on every push and pull request
to any branch.

**Jobs:**

| Job | Steps | Triggers |
|---|---|---|
| `lint` | `uv run poe lint` (ruff check + format) | every push / PR |
| `typecheck` | `uv run poe typecheck` (mypy) | every push / PR |
| `test` | `uv run poe test` + upload coverage report | every push / PR |
| `coverage-gate` | Fail if coverage < 80% (`uv run poe check-coverage`) | every push / PR |

**Acceptance criteria:**
- [ ] All four jobs run in parallel where possible (`lint` and `typecheck` are independent)
- [ ] `test` job uses a matrix of Python 3.12 only (no cross-version needed yet)
- [ ] SQLite file is created in a temp directory during test run (no external service needed)
- [ ] Coverage report artifact uploaded on every run
- [ ] Pre-commit hooks run inside `lint` job (same hooks as local dev)

**Dependencies:** Task 1

**Files touched:**
- `.github/workflows/ci.yml`

**Estimated scope:** S

### Task 19: GitHub Actions — Docker build + push

**Description:** Implement `.github/workflows/docker.yml`. Builds the Linux Docker image
and pushes it to a container registry only on push to `main`.

**Dockerfile requirements:**
- Base: `python:3.12-slim` (Linux/Debian)
- Install `libmagic1` via `apt-get` (required by `python-magic` on Linux)
- Install deps via `uv sync --no-dev` (production only)
- Expose port 8000
- Entrypoint: `uvicorn classiflow.api.app:create_app --factory --host 0.0.0.0 --port 8000`

**Acceptance criteria:**
- [ ] `docker build` succeeds locally on Linux and produces a runnable image
- [ ] `python-magic` correctly detects MIME types inside the container (libmagic installed)
- [ ] Image runs with `DATABASE_URL`, `JWT_SECRET_KEY`, `GOOGLE_CLIENT_ID/SECRET` as env vars
- [ ] CI push to `main` triggers build + push to registry
- [ ] PRs only build (no push)

**Dependencies:** Task 17

**Files touched:**
- `Dockerfile`
- `.github/workflows/docker.yml`
- `INSTALL.md` (document `libmagic1` requirement and Windows dev workaround)

**Estimated scope:** S

### Checkpoint I — Project Complete
- [ ] `uv run poe check` passes
- [ ] All tests green, coverage ≥ 80%
- [ ] CI pipeline green on GitHub
- [ ] Docker image builds and runs successfully
- [ ] Auth flow works end-to-end with a real Google account in the whitelist

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| `llama-cpp-python` not installable in CI without GPU | High | `MockLlm` for all tests; real model only in manual integration runs |
| `python-magic` requires system `libmagic1` | Medium | Install in Dockerfile via `apt-get`; document for local Linux dev; Windows devs install `python-magic-bin` manually |
| `faiss-cpu` slow on first import | Low | Lazy import inside Agent 4; only loaded when `run()` is called |
| mypy strict + LangChain generics | Medium | `type: ignore[misc]` only for LangChain internals; document each suppression |
| SSE queue leak on client disconnect | Medium | `try/finally` in async generator calls `broadcaster.close(job_id)` |
| SQLite not suitable for multi-worker deployment | Low | Single `uvicorn` worker for now; swap connection string to PostgreSQL + add `asyncpg` for production |
| Google OAuth requires live redirect URI | Low | Use `httpx.MockTransport` in tests; document local dev setup with `GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback` |

---

## Resolved Decisions

| Question | Decision |
|---|---|
| Web scraper | Not in scope for now; may be added later without changing pipeline code |
| Frontend | Not in scope; API is the delivery surface for this sprint |
| `config/` location | Project root — editable without reinstalling the package |
| File input to API | Multipart upload (`POST /pipeline/ingest`) |
| Celery | Not in scope — FastAPI `asyncio` background task is sufficient |
| Audit persistence | SQLite via `IAuditRepository` (loguru also writes a local file as backup) |
| Document tracking | `document_steps` (full per-agent path) + summary fields on `jobs` + `human_decisions` for reviewer actions; review queue served from `GET /pipeline/review-queue` |
| Domain objects | Pydantic `BaseModel` — no `@dataclass` |
| DI framework | `dependency-injector` `DeclarativeContainer` + `@inject` + `Provide` — not plain `Depends()` |
| DB in production | PostgreSQL — change `DATABASE_URL` and driver only |
| Target OS | Linux (Docker); Windows is a dev-only environment |

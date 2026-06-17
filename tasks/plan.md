# Implementation Plan: Classiflow — Ingesta Stage + API Layer

## Project Context

Classiflow is a multi-stage document classification system for Municipalidad de Rosario.
This plan covers **Stage 1: Ingesta** — the first processing boundary — and the **API + real-time
event layer** that exposes it to the frontend.

### Full pipeline (conceptual — stages beyond Ingesta are out of scope here)

```
Sources
  ├── Municipal dataset (CSV + PDFs)
  ├── Web scraping
  └── Manual upload (PDF · DOCX · img)
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

The Ingesta stage is the **first and only processing gate before content enters the system**.
Its job is to determine whether a file is **safe, valid, and new** — it never reads document
content deeply. Accepted files are handed off to Stage 2.

The stage is a sequential 4-agent chain coordinated by a LangGraph state machine.

---

## How the API Fits

The pipeline is **API-first**. The frontend calls `POST /pipeline/ingest` to submit a document.
The API creates a `job_id`, starts the pipeline as an async background task, and immediately
returns. The frontend then opens `GET /pipeline/{job_id}/events` (Server-Sent Events) to
receive real-time agent state updates as each agent starts and completes.

All pipeline agents run sequentially inside the same background task. The API does not poll;
each agent emits events through an in-memory broadcaster that pushes them to the SSE stream.

```
Frontend                     API (FastAPI)               Background Task
   │                              │                             │
   │── POST /pipeline/ingest ────►│                             │
   │◄── { job_id: "abc-123" } ───│                             │
   │                              │──── create_task() ─────────►│
   │── GET /pipeline/abc-123/events (SSE stream open)           │
   │                              │     Agent 1 starts          │
   │◄── event: agent_started ─────│◄─── emit() ────────────────│
   │◄── event: agent_passed ──────│◄─── emit() ────────────────│
   │◄── event: agent_started ─────│◄─── emit() (Agent 2) ──────│
   │         ...                  │                             │
   │◄── event: pipeline_done ─────│◄─── emit() ────────────────│
   │    (SSE stream closes)        │                             │
```

---

## Architecture Decisions

- **FastAPI as the API layer** — async, OpenAPI docs included, native SSE support via `StreamingResponse`.
- **SSE over WebSocket** — pipeline state is unidirectional server→client; SSE is simpler,
  works over standard HTTP, no connection upgrade required.
- **asyncio.Queue per job** — in-memory event broadcaster; each job gets its own queue.
  Can be replaced with Redis pub/sub later without changing agent code.
- **`llama-cpp-python` over Ollama** — embedded in-process, no HTTP round-trip, native
  grammar-constrained JSON, easier to mock in tests.
- **Shared LLM singleton** — one `Llama` instance loaded once and injected into Agent 2
  and Agent 3. Avoids reloading 2.5 GB per job.
- **LangChain for Agent 2 and Agent 3 only** — `PromptTemplate` + `JsonOutputParser`
  reduce boilerplate and allow model swaps without touching agent logic.
- **LangGraph as Coordinator** — typed state graph with conditional edges; each agent either
  passes the job forward or routes to `review_queue/` or `rejected/`.
- **AuditLogger injected into every agent** — structured per-entry logging (loguru to file);
  each agent logs its own result. The coordinator logs only routing decisions.
- **`python-magic-bin` on Windows** — bundles `libmagic` DLL; avoids system-level install.
- **Config in `config/`** at project root — editable without reinstalling the package.

---

## Dependency Graph

```
config/allowed_formats.yaml ──────────────► agent2_format_validation
config/content_validation.yaml ────────────► agent3_content_validation
config/duplicate_control.yaml ─────────────► agent4_duplicate_control

llm_provider.py ───────────────────────────► agent2_format_validation
               └───────────────────────────► agent3_content_validation

shared/audit/logger.py ────────────────────► agent1 · agent2 · agent3 · agent4 · coordinator
shared/events/broadcaster.py ──────────────► coordinator (emits agent events)
                             └─────────────► api/routes/pipeline/endpoints.py (SSE stream)

prompts/format_validation.py ──────────────► agent2_format_validation
prompts/content_validation.py ─────────────► agent3_content_validation

agent1_file_reception ─────────────────────► coordinator
agent2_format_validation ──────────────────► coordinator
agent3_content_validation ─────────────────► coordinator
agent4_duplicate_control ──────────────────► coordinator

coordinator ───────────────────────────────► api (triggered by background task)
```

---

## File Layout (target state)

```
src/classiflow/
├── __init__.py
│
├── api/                                    # FastAPI application
│   ├── __init__.py
│   ├── app.py                              # FastAPI factory (routers, error handlers)
│   ├── dependencies.py                     # Annotated DI aliases for routes
│   ├── schema.py                           # BaseSchema (Pydantic + CamelCase)
│   ├── error_handlers/
│   │   ├── __init__.py
│   │   └── pipeline.py                     # PipelineError → JSONResponse
│   └── routes/
│       ├── __init__.py
│       ├── health/
│       │   ├── __init__.py
│       │   └── endpoints.py                # GET /health
│       └── pipeline/
│           ├── __init__.py
│           ├── endpoints.py                # POST /pipeline/ingest
│           │                               # GET  /pipeline/{job_id}/events  (SSE)
│           └── schemas.py                  # IngestRequest, IngestResponse, AgentEventSchema
│
├── shared/                                 # Cross-cutting concerns (all stages use these)
│   ├── __init__.py
│   ├── audit/
│   │   ├── __init__.py
│   │   └── logger.py                       # AuditLogger, AuditEntry dataclass
│   ├── events/
│   │   ├── __init__.py
│   │   └── broadcaster.py                  # EventBroadcaster — asyncio.Queue per job_id
│   └── domain/
│       ├── __init__.py
│       └── job.py                          # JobStatus enum, AgentEvent dataclass
│
└── ingesta/                                # Stage 1 pipeline
    ├── __init__.py
    ├── coordinator.py                      # LangGraph state machine
    ├── llm_provider.py                     # get_llm() / get_llm_langchain() singletons
    ├── watcher.py                          # Optional: Watchdog daemon (--dry-run mode)
    ├── domain/
    │   ├── __init__.py
    │   ├── state.py                        # JobState TypedDict (LangGraph state)
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
        ├── format_validation.py            # PromptTemplate + JsonOutputParser
        └── content_validation.py

config/
├── allowed_formats.yaml
├── content_validation.yaml
└── duplicate_control.yaml

tests/
├── conftest.py                             # Session-level DI + TestBroadcaster override
├── ingesta/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_agent1.py
│   ├── test_agent2.py
│   ├── test_agent3.py
│   ├── test_agent4.py
│   └── test_coordinator.py
└── api/
    ├── __init__.py
    ├── conftest.py                         # TestClient fixture
    └── routes/
        └── pipeline/
            └── test_pipeline.py           # POST /ingest · SSE stream assertions
```

---

## Key Data Contracts

### AgentEvent (shared/domain/job.py)
Emitted by each agent at start and completion. Streamed to the frontend via SSE.

```python
@dataclass
class AgentEvent:
    job_id: str
    agent: str        # "agent1_file_reception" | "agent2_format_validation" | ...
    status: str       # "started" | "passed" | "failed" | "rejected" | "review" | "pipeline_done"
    timestamp: str    # ISO 8601
    detail: dict      # agent-specific payload: sha256, mime, reason, confidence, etc.
```

SSE wire format:
```
event: agent_update
data: {"job_id": "abc-123", "agent": "agent1_file_reception", "status": "passed", ...}
```

### AuditEntry (shared/audit/logger.py)
Written to log file for every agent execution. Never emitted to the frontend.

```python
@dataclass
class AuditEntry:
    job_id: str
    agent: str
    event: str            # mirrors AgentEvent.status
    timestamp: str
    duration_ms: float
    detail: dict
```

### Agent constructor pattern
Every agent receives `audit` and `broadcaster` via constructor injection.

```python
class Agent1FileReception:
    def __init__(self, audit: AuditLogger, broadcaster: EventBroadcaster) -> None: ...
    def run(self, job_id: str, path: Path) -> FileReceptionResult: ...
```

---

## Phase 1: Foundation

### Task 1: Package skeleton + dependencies

**Description:** Create all package directories with empty `__init__.py` files. Create
`config/` stub YAMLs. Add all runtime dependencies to `pyproject.toml` and run `uv sync`.

**Acceptance criteria:**
- [ ] `src/classiflow/api/`, `routes/health/`, `routes/pipeline/` exist with `__init__.py`
- [ ] `src/classiflow/shared/audit/`, `shared/events/`, `shared/domain/` exist with `__init__.py`
- [ ] `src/classiflow/ingesta/`, `ingesta/agents/`, `ingesta/prompts/`, `ingesta/domain/` exist with `__init__.py`
- [ ] `config/` exists with stub YAMLs
- [ ] `tests/ingesta/` and `tests/api/routes/pipeline/` exist with `__init__.py`
- [ ] All new deps in `pyproject.toml` under `[project] dependencies`
- [ ] `uv sync --dev` succeeds and `uv.lock` is updated
- [ ] `uv run poe check` passes

**Dependencies:** None

**New dependencies to add:**
```
fastapi>=0.115
uvicorn[standard]>=0.30
python-multipart>=0.0.9      # file upload support in FastAPI
sse-starlette>=2.1            # SSE StreamingResponse helper
langchain>=0.3
langchain-community>=0.3
langchain-core>=0.3
langgraph>=0.2
watchdog>=4.0
loguru>=0.7
python-magic-bin>=0.4         # Windows — bundles libmagic DLL
lingua-language-detector>=2.0
chardet>=5.0
sentence-transformers>=3.0
faiss-cpu>=1.7
sqlalchemy>=2.0
pyyaml>=6.0
```

Note: `llama-cpp-python` requires `CMAKE_ARGS="-DGGML_CUDA=on"` for GPU and must be installed
separately. See `INSTALL.md`.

**Files touched:**
- `pyproject.toml`, `uv.lock`
- All `__init__.py` stubs listed above
- `config/allowed_formats.yaml`, `config/content_validation.yaml`, `config/duplicate_control.yaml`

**Estimated scope:** S

### Checkpoint A
- [ ] `uv run poe lint` passes
- [ ] `uv run poe typecheck` passes
- [ ] `python -c "from classiflow.ingesta import agents; from classiflow.api import app"` succeeds

---

## Phase 2: Shared Infrastructure

### Task 2: Domain types + AuditLogger + EventBroadcaster

**Description:** Implement the three shared building blocks that every other module depends on.
`job.py` defines `AgentEvent` and `JobStatus`. `logger.py` implements `AuditLogger` (loguru
to rotating file). `broadcaster.py` implements `EventBroadcaster` with one `asyncio.Queue`
per job_id.

**Acceptance criteria:**
- [ ] `AgentEvent` dataclass is fully typed and serializable to JSON
- [ ] `JobStatus` enum covers: `STARTED`, `PASSED`, `FAILED`, `REJECTED`, `REVIEW`, `DONE`
- [ ] `AuditLogger.log(entry)` writes structured JSON line to `logs/audit.log` via loguru
- [ ] `AuditLogger.log_routing(job_id, decision, reason)` writes a routing entry
- [ ] `EventBroadcaster.emit(event)` puts event on the correct queue for `job_id`
- [ ] `EventBroadcaster.subscribe(job_id)` returns an async generator of `AgentEvent`
- [ ] `EventBroadcaster.close(job_id)` drains and removes the queue
- [ ] Unit tests cover emit → subscribe round-trip and close behaviour
- [ ] mypy strict passes

**Dependencies:** Task 1

**Files touched:**
- `src/classiflow/shared/domain/job.py`
- `src/classiflow/shared/audit/logger.py`
- `src/classiflow/shared/events/broadcaster.py`
- `tests/ingesta/test_shared.py`

**Estimated scope:** S

### Checkpoint B
- [ ] `uv run poe check` passes
- [ ] Broadcast round-trip test passes: emit an event, consume it from the async generator

---

## Phase 3: Deterministic Agents (no LLM)

### Task 3: Ingesta domain models

**Description:** Define all result dataclasses in `ingesta/domain/results.py` and `JobState`
in `ingesta/domain/state.py`. No logic here — pure typed data.

**Acceptance criteria:**
- [ ] `FileReceptionResult`, `FormatValidationResult`, `ContentValidationResult`,
  `DuplicateControlResult` are typed dataclasses with all fields from the spec
- [ ] `JobState` TypedDict includes all fields consumed by the LangGraph coordinator
- [ ] mypy strict passes; no `Any` usage

**Dependencies:** Task 1

**Files touched:**
- `src/classiflow/ingesta/domain/results.py`
- `src/classiflow/ingesta/domain/state.py`

**Estimated scope:** S

### Task 4: Agent 1 — File Reception

**Description:** Implement `agent1_file_reception.py` — the fully deterministic first gate.
Checks file existence, size bounds, computes SHA-256, detects MIME from magic bytes. Emits
`agent_started` and `agent_passed`/`agent_failed` events via `EventBroadcaster`.

**Acceptance criteria:**
- [ ] Returns `passed=False` for: missing file, empty file, file > `MAX_FILE_SIZE_MB`
- [ ] Returns `passed=True` with correct `sha256` and `detected_mime` for a valid PDF fixture
- [ ] Emits `agent_started` before processing and `agent_passed`/`agent_failed` after
- [ ] Writes `AuditEntry` with `duration_ms` and `detail` on every execution
- [ ] `run()` is fully type-annotated; mypy strict passes
- [ ] `tests/ingesta/test_agent1.py` covers all four code paths

**Dependencies:** Tasks 2, 3

**Files touched:**
- `src/classiflow/ingesta/agents/agent1_file_reception.py`
- `tests/ingesta/test_agent1.py`

**Estimated scope:** S

### Task 5: Config YAMLs + Agent 2 rule-based path

**Description:** Fill `config/allowed_formats.yaml`. Implement the rule-based (no SLM) path
of `agent2_format_validation.py`: fast-accept when MIME + extension + magic bytes agree,
fast-reject for disabled/unknown formats. The SLM escalation stub raises `NotImplementedError`.

**Acceptance criteria:**
- [ ] `config/allowed_formats.yaml` has entries for pdf, docx, image (html disabled)
- [ ] `_rule_based_check()` returns `ACCEPT` for a valid `.pdf` (magic bytes `%PDF`)
- [ ] `_rule_based_check()` returns `REJECT` for `.html` (disabled)
- [ ] `_rule_based_check()` returns `MANUAL_REVIEW` for unknown MIME
- [ ] `_rule_based_check()` returns `None` (gray zone) for MIME/extension mismatch
- [ ] Emits broadcaster events + writes audit entry on every execution
- [ ] Unit tests cover all four branches

**Dependencies:** Tasks 2, 3

**Files touched:**
- `config/allowed_formats.yaml`
- `src/classiflow/ingesta/agents/agent2_format_validation.py`
- `tests/ingesta/test_agent2.py`

**Estimated scope:** M

### Checkpoint C
- [ ] `uv run poe check` passes
- [ ] Agent 1 and Agent 2 rule-based tests pass

---

## Phase 4: LLM Integration

### Task 6: LLM Provider singleton

**Description:** Implement `llm_provider.py` with `get_llm()` (raw `llama-cpp-python`) and
`get_llm_langchain()` (LangChain `LlamaCpp` wrapper), both cached with `@lru_cache(maxsize=1)`.
Add a `MockLlm` class for tests.

**Acceptance criteria:**
- [ ] `get_llm()` and `get_llm_langchain()` are type-annotated and return the correct types
- [ ] Calling `get_llm()` twice returns the same instance (cache verified in test)
- [ ] `MockLlm` can substitute wherever `Llama` is expected
- [ ] `llama_cpp` import is guarded: `TYPE_CHECKING` + runtime `try/except` with a clear error
- [ ] mypy passes

**Dependencies:** Task 1

**Files touched:**
- `src/classiflow/ingesta/llm_provider.py`
- `tests/ingesta/test_llm_provider.py`

**Estimated scope:** S

### Task 7: Agent 2 — SLM escalation path + LangChain prompts

**Description:** Fill `prompts/format_validation.py` with `PromptTemplate` + `JsonOutputParser`
for `FormatDecision`. Wire `_slm_check()` in `agent2_format_validation.py`, replacing the
`NotImplementedError` stub.

**Acceptance criteria:**
- [ ] `FormatDecision` Pydantic model matches spec schema
- [ ] `build_format_chain(llm)` returns a LangChain LCEL chain
- [ ] `_slm_check()` invokes the chain and returns `FormatValidationResult` with `used_slm=True`
- [ ] `run()` end-to-end: gray-zone input → calls `_slm_check()` → emits broadcaster event
- [ ] Tests mock the LLM; no real model required

**Dependencies:** Tasks 5, 6

**Files touched:**
- `src/classiflow/ingesta/prompts/format_validation.py`
- `src/classiflow/ingesta/agents/agent2_format_validation.py`
- `tests/ingesta/test_agent2.py`

**Estimated scope:** M

### Task 8: Agent 3 — Content Validation (rules + SLM)

**Description:** Implement `agent3_content_validation.py` with rule-based checks (language
detection via `lingua`, encoding via `chardet`, min char count) and SLM escalation via
`prompts/content_validation.py`. Fill `config/content_validation.yaml`.

**Acceptance criteria:**
- [ ] Returns `passed=False` for text shorter than `MIN_CHARS`
- [ ] Returns `passed=False` + `needs_agent_review=True` for non-Spanish text
- [ ] Returns `passed=True` for a valid Spanish text sample
- [ ] `_slm_legitimacy_check()` calls `build_content_chain(llm)` and returns parsed dict
- [ ] `LegitimacyDecision` Pydantic model matches spec schema
- [ ] Emits broadcaster events + writes audit entry on every execution
- [ ] Tests cover all paths using `MockLlm`

**Dependencies:** Tasks 2, 3, 6

**Files touched:**
- `config/content_validation.yaml`
- `src/classiflow/ingesta/prompts/content_validation.py`
- `src/classiflow/ingesta/agents/agent3_content_validation.py`
- `tests/ingesta/test_agent3.py`

**Estimated scope:** M

### Checkpoint D
- [ ] `uv run poe check` passes
- [ ] Agents 1–3 tests pass; agents 2 and 3 callable end-to-end with `MockLlm`

---

## Phase 5: Duplicate Control

### Task 9: Agent 4 — Duplicate Control

**Description:** Implement `agent4_duplicate_control.py` with two-layer detection: exact
SHA-256 hash check (dict-backed in tests) and semantic near-duplicate via
`sentence-transformers` + FAISS. Fill `config/duplicate_control.yaml`.

**Acceptance criteria:**
- [ ] Layer 1: exact SHA-256 match returns `duplicate_type="exact"`, `similarity_score=1.0`
- [ ] Layer 2: cosine similarity > threshold returns `duplicate_type="semantic"`
- [ ] New document: returns `is_duplicate=False`, updates hash store
- [ ] Emits broadcaster events + writes audit entry on every execution
- [ ] Tests use an in-memory dict for the hash store and a small FAISS index
- [ ] `sentence-transformers` model load is lazy (not at import time)

**Dependencies:** Tasks 2, 3

**Files touched:**
- `config/duplicate_control.yaml`
- `src/classiflow/ingesta/agents/agent4_duplicate_control.py`
- `tests/ingesta/test_agent4.py`

**Estimated scope:** M

### Checkpoint E
- [ ] `uv run poe check` passes
- [ ] All four agent tests pass

---

## Phase 6: Orchestration

### Task 10: Coordinator — LangGraph state machine

**Description:** Implement `coordinator.py` using LangGraph. Defines `JobState`, one node
per agent, and conditional edges routing to `accept`, `reject`, or `queue_review`. Loads
the LLM singleton once at startup and injects it. Logs routing decisions to `AuditLogger`.

```
              ┌──────────────────────────────────────────────────┐
job_start ───►│ agent1 ──► agent2 ──► agent3 ──► agent4        │
              │    │           │           │           │         │
              │  reject    reject/     review/     duplicate     │
              │            review      reject      /new          │
              └──────┬──────────┬──────────┬──────────┬─────────┘
                     ▼          ▼          ▼          ▼
                  rejected   review     review     accepted
```

**Acceptance criteria:**
- [ ] `JobState` TypedDict has all required fields
- [ ] Graph edges match routing logic above
- [ ] `handle_accept`, `handle_reject`, `handle_review` write to `AuditLogger`
- [ ] Coordinator emits `pipeline_done` event via `EventBroadcaster` on terminal state
- [ ] End-to-end integration test: valid PDF passes all 4 agents → `accept`
- [ ] End-to-end test: empty file rejected at agent 1
- [ ] Uses `MockLlm`; no real model required

**Dependencies:** Tasks 4, 7, 8, 9

**Files touched:**
- `src/classiflow/ingesta/coordinator.py`
- `tests/ingesta/test_coordinator.py`

**Estimated scope:** L

### Task 11: Watcher daemon (optional trigger)

**Description:** Implement `watcher.py` using Watchdog as an alternative trigger. Monitors
`/storage/landing/`, copies new files to `/storage/processing/{job_id}/`, calls the
coordinator. Includes a `--dry-run` flag for local testing without Celery.

**Acceptance criteria:**
- [ ] `LandingZoneHandler.on_created()` generates a UUID job_id and copies the file
- [ ] `--dry-run` invokes `coordinator.run_pipeline()` directly (synchronous, no Celery)
- [ ] Duplicate events for the same file within 1 second are debounced
- [ ] First audit entry written with `source`, `timestamp`, `original_filename`

**Dependencies:** Task 10

**Files touched:**
- `src/classiflow/ingesta/watcher.py`

**Estimated scope:** S

---

## Phase 7: API Layer

### Task 12: FastAPI application + health route

**Description:** Implement `api/app.py` (FastAPI factory), `api/schema.py` (BaseSchema),
`api/error_handlers/`, and `routes/health/endpoints.py`. Wire everything in `api/app.py`.

**Acceptance criteria:**
- [ ] `create_app()` returns a `FastAPI` instance with all routers and error handlers mounted
- [ ] `GET /health` returns `{"status": "ok"}` and HTTP 200
- [ ] `BaseSchema` uses `alias_generator=to_camel` and `populate_by_name=True`
- [ ] `uv run poe test tests/api/` passes

**Dependencies:** Task 1

**Files touched:**
- `src/classiflow/api/app.py`
- `src/classiflow/api/schema.py`
- `src/classiflow/api/error_handlers/__init__.py`
- `src/classiflow/api/routes/health/endpoints.py`
- `tests/api/conftest.py`
- `tests/api/routes/pipeline/test_pipeline.py`

**Estimated scope:** S

### Task 13: Pipeline ingestion endpoint + SSE stream

**Description:** Implement the two pipeline routes:
- `POST /pipeline/ingest` — accepts a file upload, creates a `job_id`, starts the
  coordinator as an asyncio background task, returns `{"job_id": "..."}` immediately.
- `GET /pipeline/{job_id}/events` — returns an SSE stream. Subscribes to the
  `EventBroadcaster` for the given `job_id` and pushes each `AgentEvent` as it arrives.
  Closes when `pipeline_done` is received or the client disconnects.

**Acceptance criteria:**
- [ ] `POST /pipeline/ingest` returns HTTP 202 with `job_id` within 100 ms (no blocking)
- [ ] SSE stream emits `agent_started` and `agent_passed`/`agent_failed` for each agent
- [ ] SSE stream emits `pipeline_done` as the final event and closes
- [ ] Disconnecting the SSE client before completion does not leak the queue
- [ ] `IngestRequest`, `IngestResponse`, `AgentEventSchema` are fully typed Pydantic models
- [ ] Tests assert the SSE event sequence for a happy-path ingest (using `MockLlm` + small fixture PDF)
- [ ] Tests assert HTTP 404 for `GET /pipeline/unknown-id/events`

**Dependencies:** Tasks 2, 10, 12

**Files touched:**
- `src/classiflow/api/routes/pipeline/endpoints.py`
- `src/classiflow/api/routes/pipeline/schemas.py`
- `src/classiflow/api/dependencies.py`
- `tests/api/routes/pipeline/test_pipeline.py`

**Estimated scope:** L

### Checkpoint F — Final
- [ ] `uv run poe check` passes (lint + typecheck + nbtest)
- [ ] `uv run poe test` — all tests green
- [ ] Manual smoke test:
  ```bash
  uv run uvicorn classiflow.api.app:create_app --factory --reload
  curl -X POST http://localhost:8000/pipeline/ingest -F "file=@tests/fixtures/decreto_sample.pdf"
  # copy job_id from response
  curl -N http://localhost:8000/pipeline/{job_id}/events
  # observe SSE stream: agent_started → agent_passed × 4 → pipeline_done
  ```

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `llama-cpp-python` not installable in CI without GPU | High | `MockLlm` for all tests; real model only in manual integration runs |
| `python-magic-bin` not finding `libmagic` on Windows | Medium | `python-magic-bin` bundles DLL; document in `INSTALL.md` |
| `faiss-cpu` import slow on first use | Low | Lazy import inside agent 4; only loaded when `run()` is called |
| mypy strict + LangChain generics | Medium | `type: ignore[misc]` only for LangChain internals; document each suppression |
| SSE queue leak if client disconnects mid-stream | Medium | `try/finally` in the async generator calls `broadcaster.close(job_id)` |
| asyncio.Queue not suitable for multi-process deployment | Low | Single-process uvicorn is fine for now; document Redis pub/sub upgrade path |

## Open Questions

1. Should `config/` live at project root or inside `src/classiflow/ingesta/`? *(Root recommended — editable without reinstalling the package.)*
2. Should `/pipeline/ingest` accept a file upload (multipart) or a file path (JSON body)? *(Multipart for production; file-path mode for `--dry-run` CLI use.)*
3. Is Celery in scope for this sprint? *(No — watcher uses `--dry-run`; FastAPI uses asyncio background task.)*
4. Should the audit log also write to a SQLAlchemy DB or loguru file only? *(Loguru file for now; DB is a future upgrade.)*

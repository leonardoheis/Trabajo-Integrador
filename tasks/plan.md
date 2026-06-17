# Implementation Plan: Ingesta Pipeline

## Overview

Build the Ingesta stage of ClassiFlow — the first processing boundary. Its sole responsibility is determining whether a file is **safe, valid, and new** before passing it downstream to text extraction. It never reads document content deeply; that belongs to the next stage.

The pipeline is a sequential 4-agent chain coordinated by a LangGraph state machine, triggered by a Watchdog daemon monitoring the landing zone.

## Architecture Decisions

- **`llama-cpp-python` over Ollama** — embedded in-process, no HTTP round-trip, native grammar-constrained JSON, easier to mock in tests.
- **Shared LLM singleton** — one `Llama` instance loaded once by the Coordinator and injected into Agent 2 and Agent 3. Avoids reloading 2.5 GB per job.
- **LangChain for Agent 2 and Agent 3 only** — `PromptTemplate` + `JsonOutputParser` reduce boilerplate and allow model swaps without touching agent logic. Not used in Agent 1 (no model) or Agent 4 (embeddings, not generative).
- **LangGraph as Coordinator** — models the pipeline as a typed state graph with conditional edges; each agent either passes the job forward or routes to `review_queue/` or `rejected/`.
- **Vertical task slices** — each task delivers a working, independently testable unit. No horizontal layers.
- **`python-magic-bin` on Windows** — `python-magic` requires `libmagic`; on Windows use `python-magic-bin` which bundles the DLL.
- **Config in `config/`** at project root — keeps YAML files editable without touching source; Agent 2 reads `allowed_formats.yaml` at runtime.

## Dependency Graph

```
config/allowed_formats.yaml ──────────► agent2_format_validation
config/content_validation.yaml ────────► agent3_content_validation
config/duplicate_control.yaml ─────────► agent4_duplicate_control

llm_provider.py ───────────────────────► agent2_format_validation
               └───────────────────────► agent3_content_validation

prompts/format_validation.py ──────────► agent2_format_validation
prompts/content_validation.py ─────────► agent3_content_validation

agent1_file_reception ─────────────────► coordinator
agent2_format_validation ──────────────► coordinator
agent3_content_validation ─────────────► coordinator
agent4_duplicate_control ──────────────► coordinator

coordinator ───────────────────────────► watcher (triggered by)
```

Implementation order follows this graph bottom-up.

## File Layout (target state)

```
src/classiflow/ingesta/
├── __init__.py
├── watcher.py
├── coordinator.py
├── llm_provider.py
├── prompts/
│   ├── __init__.py
│   ├── format_validation.py
│   └── content_validation.py
└── agents/
    ├── __init__.py
    ├── agent1_file_reception.py
    ├── agent2_format_validation.py
    ├── agent3_content_validation.py
    └── agent4_duplicate_control.py

config/
├── allowed_formats.yaml
├── content_validation.yaml
└── duplicate_control.yaml

tests/ingesta/
├── __init__.py
├── test_agent1.py
├── test_agent2.py
├── test_agent3.py
├── test_agent4.py
└── test_coordinator.py
```

---

## Phase 1: Foundation

### Task 1: Package skeleton + dependencies

**Description:** Create the `src/classiflow/ingesta/` package tree (empty `__init__.py` files), `config/` directory, and `tests/ingesta/`. Add all runtime dependencies to `pyproject.toml` and run `uv sync` to lock them.

**Acceptance criteria:**
- [ ] `src/classiflow/ingesta/`, `src/classiflow/ingesta/agents/`, `src/classiflow/ingesta/prompts/` exist with `__init__.py`
- [ ] `config/` exists with stub YAMLs
- [ ] `tests/ingesta/` exists with `__init__.py`
- [ ] All new deps in `pyproject.toml` under `[project] dependencies`
- [ ] `uv sync --dev` succeeds and `uv.lock` is updated
- [ ] `uv run poe check` passes (empty modules have no type errors)

**Dependencies:** None

**Files touched:**
- `pyproject.toml`
- `uv.lock`
- `src/classiflow/ingesta/__init__.py` (new)
- `src/classiflow/ingesta/agents/__init__.py` (new)
- `src/classiflow/ingesta/prompts/__init__.py` (new)
- `config/allowed_formats.yaml` (stub)
- `config/content_validation.yaml` (stub)
- `config/duplicate_control.yaml` (stub)
- `tests/ingesta/__init__.py` (new)

**Estimated scope:** S

**New dependencies to add:**
```
langchain>=0.3
langchain-community>=0.3
langchain-core>=0.3
langgraph>=0.2
watchdog>=4.0
celery[redis]>=5.3
redis>=5.0
loguru>=0.7
python-magic-bin>=0.4   # Windows — bundles libmagic DLL
lingua-language-detector>=2.0
chardet>=5.0
sentence-transformers>=3.0
faiss-cpu>=1.7
sqlalchemy>=2.0
pyyaml>=6.0
```

Note: `llama-cpp-python` is NOT added to `pyproject.toml` — it requires `CMAKE_ARGS="-DGGML_CUDA=on"` for GPU and must be installed manually or via a separate install script. Add an `# install separately` comment in a `INSTALL.md` or inline in `llm_provider.py`.

### Checkpoint A
- [ ] `uv run poe lint` passes
- [ ] `uv run poe typecheck` passes
- [ ] Package imports cleanly: `python -c "from classiflow.ingesta import agents"`

---

## Phase 2: Deterministic Agents (no LLM)

### Task 2: Agent 1 — File Reception

**Description:** Implement `agent1_file_reception.py` — the fully deterministic first gate. Checks file existence, size bounds, computes SHA-256, and detects MIME from magic bytes. No model call. Includes unit tests with temp files.

**Acceptance criteria:**
- [ ] `FileReceptionResult` dataclass with all fields typed
- [ ] Returns `passed=False` for: missing file, empty file, file > `MAX_FILE_SIZE_MB`
- [ ] Returns `passed=True` with correct `sha256` and `detected_mime` for a valid PDF fixture
- [ ] `run()` is fully type-annotated (mypy strict passes)
- [ ] `tests/ingesta/test_agent1.py` covers all four code paths

**Dependencies:** Task 1

**Files touched:**
- `src/classiflow/ingesta/agents/agent1_file_reception.py`
- `tests/ingesta/test_agent1.py`

**Estimated scope:** S

### Task 3: Config YAMLs + Agent 2 rule-based path

**Description:** Fill in `config/allowed_formats.yaml` with the full format rules from the spec. Implement the rule-based (no SLM) path of `agent2_format_validation.py`: fast-accept when MIME + extension + magic bytes agree, fast-reject for disabled/unknown formats. The SLM escalation stub raises `NotImplementedError` until Task 5.

**Acceptance criteria:**
- [ ] `config/allowed_formats.yaml` has entries for pdf, docx, image, html (html disabled)
- [ ] `_rule_based_check()` returns `ACCEPT` for a valid `.pdf` file (magic bytes = `%PDF`)
- [ ] `_rule_based_check()` returns `REJECT` for an `.html` file (disabled)
- [ ] `_rule_based_check()` returns `MANUAL_REVIEW` for an unknown MIME
- [ ] `_rule_based_check()` returns `None` (gray zone) for MIME/extension mismatch
- [ ] Unit tests cover all four branches
- [ ] `run()` calls `_rule_based_check()` and raises `NotImplementedError` for gray zone

**Dependencies:** Task 1

**Files touched:**
- `config/allowed_formats.yaml`
- `src/classiflow/ingesta/agents/agent2_format_validation.py`
- `tests/ingesta/test_agent2.py`

**Estimated scope:** M

### Checkpoint B
- [ ] `uv run poe check` passes
- [ ] `uv run poe test` passes for `tests/ingesta/test_agent1.py` and `test_agent2.py`

---

## Phase 3: LLM Integration

### Task 4: LLM Provider singleton

**Description:** Implement `llm_provider.py` with two functions: `get_llm()` (raw `llama-cpp-python`) and `get_llm_langchain()` (LangChain `LlamaCpp` wrapper). Both use `@lru_cache(maxsize=1)`. Add a `MockLlm` class for tests that returns a fixed JSON string without loading the GGUF model.

**Acceptance criteria:**
- [ ] `get_llm()` and `get_llm_langchain()` are type-annotated and return the correct types
- [ ] Calling `get_llm()` twice returns the same instance (cache)
- [ ] `MockLlm` can be substituted wherever `Llama` is expected
- [ ] Module-level `llama_cpp` import is guarded: `TYPE_CHECKING` import + runtime try/except with a helpful error message if not installed
- [ ] mypy passes (use `type: ignore` comment only if strictly necessary, document why)

**Dependencies:** Task 1

**Files touched:**
- `src/classiflow/ingesta/llm_provider.py`
- `tests/ingesta/test_llm_provider.py`

**Estimated scope:** S

### Task 5: Agent 2 — SLM escalation path + LangChain prompts

**Description:** Fill in `prompts/format_validation.py` with the `PromptTemplate` and `JsonOutputParser` for `FormatDecision`. Wire it into `agent2_format_validation.py`'s `_slm_check()` — replacing the `NotImplementedError` stub. Tests use `MockLlm`.

**Acceptance criteria:**
- [ ] `FormatDecision` Pydantic model matches spec schema
- [ ] `build_format_chain(llm)` returns a LangChain LCEL chain
- [ ] `_slm_check()` invokes the chain and returns a `FormatValidationResult` with `used_slm=True`
- [ ] `run()` end-to-end: gray-zone input → calls `_slm_check()` → returns valid result
- [ ] Tests mock the LLM; no real model required to pass

**Dependencies:** Tasks 3, 4

**Files touched:**
- `src/classiflow/ingesta/prompts/format_validation.py`
- `src/classiflow/ingesta/agents/agent2_format_validation.py`
- `tests/ingesta/test_agent2.py`

**Estimated scope:** M

### Task 6: Agent 3 — Content Validation (rules + SLM)

**Description:** Implement `agent3_content_validation.py` with rule-based checks (language detection via `lingua`, encoding via `chardet`, minimum char count) and the SLM escalation path via `prompts/content_validation.py`. Fill `config/content_validation.yaml`.

**Acceptance criteria:**
- [ ] `ContentValidationResult` dataclass fully typed
- [ ] Returns `passed=False` for text shorter than `MIN_CHARS`
- [ ] Returns `passed=False` + `needs_agent_review=True` for non-Spanish text
- [ ] Returns `passed=True` for a valid Spanish text sample
- [ ] `_slm_legitimacy_check()` calls `build_content_chain(llm)` and returns parsed dict
- [ ] `LegitimacyDecision` Pydantic model matches spec schema
- [ ] Tests cover all code paths using `MockLlm`

**Dependencies:** Tasks 4, 1

**Files touched:**
- `config/content_validation.yaml`
- `src/classiflow/ingesta/prompts/content_validation.py`
- `src/classiflow/ingesta/agents/agent3_content_validation.py`
- `tests/ingesta/test_agent3.py`

**Estimated scope:** M

### Checkpoint C
- [ ] `uv run poe check` passes
- [ ] `uv run poe test` passes for agents 1-3
- [ ] Agents 2 and 3 can be called end-to-end with `MockLlm`

---

## Phase 4: Duplicate Control

### Task 7: Agent 4 — Duplicate Control

**Description:** Implement `agent4_duplicate_control.py` with two-layer detection: exact SHA-256 hash check (dict-based in tests, DB-backed in prod) and semantic near-duplicate via `sentence-transformers` + FAISS. Fill `config/duplicate_control.yaml` with the similarity threshold.

**Acceptance criteria:**
- [ ] `DuplicateControlResult` dataclass fully typed
- [ ] Layer 1: exact SHA-256 match returns `duplicate_type="exact"`, `similarity_score=1.0`
- [ ] Layer 2: cosine similarity > threshold returns `duplicate_type="semantic"`
- [ ] New document: returns `is_duplicate=False`, updates hash store
- [ ] Tests use an in-memory dict for the hash store and a small FAISS index
- [ ] `sentence-transformers` model load is lazy (not at import time)

**Dependencies:** Task 1

**Files touched:**
- `config/duplicate_control.yaml`
- `src/classiflow/ingesta/agents/agent4_duplicate_control.py`
- `tests/ingesta/test_agent4.py`

**Estimated scope:** M

### Checkpoint D
- [ ] `uv run poe check` passes
- [ ] All agent tests pass

---

## Phase 5: Orchestration

### Task 8: Coordinator — LangGraph state machine

**Description:** Implement `coordinator.py` using LangGraph. Defines `JobState` TypedDict, one node per agent, and conditional edges that route to `accept`, `reject`, or `queue_review` based on each agent's result. Loads the LLM singleton once at startup and injects it.

**Acceptance criteria:**
- [ ] `JobState` TypedDict has all required fields
- [ ] Graph edges match the routing logic in the spec (each agent result checked before proceeding)
- [ ] `handle_accept`, `handle_reject`, `handle_review` write to the audit log
- [ ] End-to-end integration test: a valid PDF fixture passes all 4 agents and reaches `accept`
- [ ] End-to-end test: an empty file is rejected at agent 1
- [ ] Uses `MockLlm`; no real model required for tests

**Dependencies:** Tasks 2, 5, 6, 7

**Files touched:**
- `src/classiflow/ingesta/coordinator.py`
- `tests/ingesta/test_coordinator.py`

**Estimated scope:** L

### Task 9: Watcher daemon

**Description:** Implement `watcher.py` using Watchdog. Monitors `/storage/landing/`, copies new files to `/storage/processing/{job_id}/`, and triggers the Coordinator. Includes a `--dry-run` flag for local testing without a Celery worker.

**Acceptance criteria:**
- [ ] `LandingZoneHandler.on_created()` generates a UUID job ID and copies the file
- [ ] `--dry-run` invokes `coordinator.run_pipeline()` directly (synchronous, no Celery)
- [ ] Duplicate `on_created` events for the same file within 1 second are debounced
- [ ] First audit log entry written with `source`, `timestamp`, `original_filename`

**Dependencies:** Task 8

**Files touched:**
- `src/classiflow/ingesta/watcher.py`

**Estimated scope:** S

### Checkpoint E — Final
- [ ] `uv run poe check` passes (lint + typecheck + nbtest)
- [ ] `uv run poe test` passes — all ingesta tests green
- [ ] End-to-end dry-run: `python -m classiflow.ingesta.watcher --dry-run --file tests/fixtures/decreto_sample.pdf`

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `llama-cpp-python` not installable in CI without GPU | High | `MockLlm` for all tests; real model only in manual integration runs |
| `python-magic-bin` not finding `libmagic` on Windows | Medium | Use `python-magic-bin` (bundles DLL); document in `INSTALL.md` |
| `faiss-cpu` import slow on first use | Low | Lazy import inside `agent4`; only loaded when `run()` is called |
| mypy strict + LangChain's complex generics | Medium | Use `type: ignore[misc]` only for LangChain internals; document each suppression |
| Celery/Redis not available in dev | Low | `--dry-run` flag bypasses queue; watcher runs synchronously |

## Open Questions

1. Should `config/` live at project root or inside `src/classiflow/ingesta/`? (Root keeps it editable without reinstalling the package — recommended.)
2. Should `storage/` paths be configurable via env vars or only via CLI args to the watcher?
3. Is Celery in scope for this sprint or should watcher always use `--dry-run` mode for now?

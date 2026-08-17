# Classiflow

A multi-agent document classification system for Municipalidad de Rosario (Argentina).

Classiflow ingests municipal documents from multiple sources, extracts and enriches their content, classifies them using LLM agents with confidence scoring, and exposes the results through a chat interface and a web UI.

## Architecture

```
Sources (inputs)
  ├── Municipal dataset (CSV + PDFs)
  ├── Web scraping
  └── Manual upload (PDF · DOCX · img)
          │
          ▼
  ┌─────────────────────────────────────────────┐
  │                 Orchestrator                │
  │                                             │
  │  Ingestion ──► Text extraction              │
  │                     │                       │
  │              Refinement and enrichment      │
  │                     │                       │
  │  ┌──────────────────────────────────────┐   │
  │  │  Ingestion agent                     │   │
  │  │  receives · validates · detects lang │   │
  │  │                                      │   │
  │  │  Classification agent                │   │
  │  │  document type · confidence score    │   │
  │  │                                      │   │
  │  │  Confidence gate                     │   │
  │  │  auto · review · escalation          │   │
  │  │                                      │   │
  │  │  Routing agent                       │   │
  │  │  directory · audit log               │   │
  │  └──────────────────────────────────────┘   │
  └─────────────────────────────────────────────┘
          │
          ├── Knowledge base (chunks · vectors · sources)
          │         │
          │   Chat agent (query · retrieve · respond with sources)
          │
          ├── Outputs
          │     ├── Classified documents
          │     ├── Review queue (low confidence)
          │     └── Audit log (every decision)
          │
          └── Web interface
                upload · agent visualization · classification · chat
```

## Stage 1 — Ingesta Pipeline (done — merged to `main` via [PR #17](https://github.com/leonardoheis/Trabajo-Integrador/pull/17))

Stage 1 is the first and only processing gate before a document enters the system.
It determines whether a file is **safe, valid, and new** — it never classifies content.
Text extraction (MarkItDown → EasyOCR fallback) runs inline within this stage, ahead of
node3. Accepted files are handed off to Stage 2 (extraction hardening — bounded
concurrency + observability, not re-extraction) already carrying their extracted text.

### How a file moves through the nodes

```
[FILE UPLOAD]  ordenanza_2026.pdf
       │
       ▼
┌─────────────┐
│   NODE 1    │  File Reception
│             │  · file present? not empty? size ≤ limit?
│             │  · compute SHA-256
│             │  · detect MIME type (python-magic)
└──────┬──────┘
       │ passed=True
       │ passed=False ──────────────────────────────► REJECTED  (malformed / missing)
       ▼
┌─────────────┐
│   NODE 2    │  Format Validation
│             │  · magic bytes match MIME? extension consistent?
│             │  · known-mismatches lookup table (config)
│             │  · gray zone → Phi-4-mini SLM decides
└──────┬──────┘
       │ passed=True
       │ passed=False ──────────────────────────────► REJECTED  (wrong format)
       │ needs_manual_review ───────────────────────► REVIEW QUEUE
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│   EXTRACTION   (ExtractionStep node — Stage 2, bounded by a      │
│                 Container-injected asyncio.Semaphore, SSE +      │
│                 DocumentStep observability like node1-4)         │
│                                                                  │
│   Attempt 1 — MarkItDown  (tables, columns, bad encodings)       │
│       ├─ chars ≥ min_chars (50) ─────────────────────────────► ✓ │
│       └─ chars < min_chars ──────────────────────────────────► OCR │
│                                                                  │
│   Attempt 2 — EasyOCR  (fast, CPU, clean scans)                  │
│       ├─ chars ≥ min_usable (20) ──────────────────────────────► ✓ │
│       └─ chars < min_usable ─────────────► requires_ocr=True, human review │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
       │  text: str
       ▼
┌─────────────┐
│   NODE 3    │  Content Validation
│             │  · length ≥ min_chars?
│             │  · language = Spanish? (lingua detector)
│             │  · SLM legitimacy check (Phi-4-mini)
└──────┬──────┘
       │ passed=True
       │ passed=False (too short) ──────────────────► REJECTED
       │ passed=False (non-Spanish) ────────────────► REVIEW QUEUE  (human: translate? reject?)
       │ passed=False (not legitimate) ────────────► REJECTED or REVIEW QUEUE
       ▼
┌─────────────┐
│   NODE 4    │  Duplicate Control
│             │  · SHA-256 exact match → exact duplicate
│             │  · cosine similarity > threshold → near-duplicate
│             │  · new document → save hash
└──────┬──────┘
       │ is_duplicate=False
       ▼
    ACCEPTED → Stage 2 (extraction hardening) → Stage 3 (enrichment) → Stage 4 (classification)
```

### Text extraction retry circuit

| Attempt | Tool | Trigger | Notes |
|---------|------|---------|-------|
| 1 | **MarkItDown** | always | Handles tables, columns, bad encodings, complex layouts. No model needed. |
| 2 | **EasyOCR** | `len(text) < 50` | Pixel-level OCR, CPU-only, good for clean scans. Routes to review if `len(text) < 20` after this. |

Both extractors run inline inside the Stage 1 Coordinator's `_extract` step, ahead of
node3 — extraction is fully done by the time a job reaches content validation. Stage 2
adds bounded concurrency and SSE/DB observability around this existing step; it does
not re-extract anything.

### Routing outcomes

| Outcome | Meaning | Next step |
|---------|---------|-----------|
| `ACCEPTED` | All 4 nodes passed | Stage 2 (extraction hardening) |
| `REJECTED` | Hard failure at any node | Audit log, no retry |
| `REVIEW QUEUE` | Ambiguous result, or no usable text even after OCR | Human reviewer decides |

## Repository Structure

```
/
├── .claude/                        Claude Code project settings
├── documents/                      Reference documents and architecture diagrams
├── docs/superpowers/specs/         Architecture design specs (superpowers:brainstorming)
├── config/                         YAML config, one file per ingesta stage
│   ├── allowed_formats.yaml · content_validation.yaml
│   └── duplicate_control.yaml · extraction.yaml
├── models/                         SLM + embedding model weights (gitignored — see "Models" below)
├── src/
│   └── classiflow/                 Main Python package
│       ├── settings.py             pydantic-settings config (DATABASE_URL, JWT_*, model paths, etc.)
│       ├── domain/                 job.py (NodeEvent, JobStatus) · user.py (User, AuthToken) ·
│       │                           base.py (BaseEntity) · repositories/ (Protocol interfaces)
│       ├── database/                base.py (async engine/session) · models.py (ORM, 6 tables) ·
│       │                           repositories/ (Sql*/InMemory* implementations)
│       ├── events/
│       │   └── broadcaster.py      EventBroadcaster — asyncio.Queue per job_id, SSE source
│       ├── services/
│       │   ├── auth/               jwt.py · oauth.py · service.py (Google OAuth + whitelist)
│       │   ├── audit/               service.py (AuditService) + repository.py
│       │   └── pipeline/            service.py (PipelineService — orchestrates the coordinator)
│       ├── ingesta/                 Stage 1+2 — ingestion, validation, extraction
│       │   ├── coordinator.py       build_coordinator() — LangGraph state machine
│       │   ├── extract.py           TextExtractor — MarkItDown → EasyOCR fallback chain
│       │   ├── config*.py           AllowedFormatsConfig · ContentValidationConfig ·
│       │   │                       DuplicateControlConfig · ExtractionConfig (+ config_loader.py)
│       │   ├── llm_provider.py      get_llm_langchain() (@lru_cache) + MockLlm
│       │   ├── exceptions.py       LlmProviderError · ModelNotFoundError · ModelLoadError
│       │   ├── extractors/          MarkItDownExtractor · OCRExtractor · exceptions
│       │   ├── nodes/               base.py (BaseNode) · node1-4 · extraction_step.py
│       │   ├── domain/              context.py (JobContext) · results.py · state.py (JobState, NodeUpdate)
│       │   └── prompts/            format_validation.py · content_validation.py — SLM chain builders
│       ├── api/                    FastAPI application
│       │   ├── app.py · runner.py · dependencies.py (DI-wired Depends() aliases)
│       │   ├── routes/             auth/ · health/ · pipeline/ (ingest, SSE events, review queue)
│       │   └── error_handlers/     typed exception → JSONResponse handlers
│       ├── injections/             production.py (Container) · test.py (TestContainer)
│       └── playground/             stage1/ (7 demo notebooks) · stage2/ (concurrency demo) ·
│                                   samples/ (sample PDFs the notebooks depend on)
├── alembic/versions/                0001 initial schema · 0002 rename agent→node ·
│                                   0003 add Job.extracted_text
├── tasks/                          plan_stageN.md + todo_stageN.md per stage (1–5)
├── pyproject.toml                  Dependencies and tool configuration (managed by uv)
└── uv.lock                         Locked dependency graph
```

## Build Status

**Stage 1 closed** — merged to `main` via [PR #17](https://github.com/leonardoheis/Trabajo-Integrador/pull/17). 18 / 19 Stage-1 tasks complete · 1 pending (T22, not blocking).

| Task | Description | Status |
|------|-------------|--------|
| T01 | Package skeleton + dependencies | ✅ done |
| T02 | Database models + Alembic migration | ✅ done |
| T03 | Repository implementations | ✅ done |
| T04 | JWT utilities | ✅ done |
| T05 | Google OAuth + whitelist | ✅ done |
| T06 | JWT auth dependency | ✅ done |
| T07 | Shared domain + AuditService + EventBroadcaster | ✅ done |
| T08 | Ingesta domain models | ✅ done |
| T09 | Node 1 — File Reception | ✅ done |
| T10 | Node 2 — Format Validation (rule-based) | ✅ done |
| T11 | LLM Provider singleton | ✅ done |
| T12 | Node 2 — SLM escalation path | ✅ done |
| T13 | Node 3 — Content Validation | ✅ done |
| T14 | Node 4 — Duplicate Control | ✅ done |
| T15 | Coordinator — LangGraph | ✅ done |
| T16 | FastAPI app + health route | ✅ done |
| T17 | Pipeline endpoints + SSE stream | ✅ done |
| T21 | Text extraction — MarkItDown + EasyOCR fallback | ✅ done |
| T22 | Bulk document ingest endpoint | 🔲 pending |

GitHub Actions CI, Docker build+push, and wandb tracing (formerly T18-T20) don't gate
pipeline functionality — moved to Stage 4, see [`tasks/todo_stage4.md`](tasks/todo_stage4.md).

Full task details and dependency graph: [tasks/todo.md](tasks/todo.md) ·
[Stage 2 plan](tasks/plan_stage2.md) · [Stage 2 tasks](tasks/todo_stage2.md)

**Stage 2 implemented** — bounded concurrency and full SSE/DB observability around Stage
1's existing text-extraction step (MarkItDown → EasyOCR fallback); no re-extraction. Also
fixed several hidden-dependency singletons (`get_language_detector`,
`get_sentence_model`/`embedding_store`, node2/node3 SLM chains) by wiring them through the
DI `Container`, matching the existing `broadcaster`/`text_extractor` pattern. All 7 tasks
committed to `feat/extraction-hardening`; open for merge to `main` via
[PR #20](https://github.com/leonardoheis/Trabajo-Integrador/pull/20).

| Task | Description | Status |
|------|-------------|--------|
| S2-T01 | `ExtractionConfig` | ✅ done |
| S2-T02 | `ExtractionResult` domain entity | ✅ done |
| S2-T03 | Bounded concurrency (`asyncio.Semaphore`, Container-injected) | ✅ done |
| S2-T04 | `ExtractionStep` + `DocumentStep` observability | ✅ done |
| S2-T05 | Integration test — concurrency + observability | ✅ done |
| S2-T06 | Relocate models to project root + document download sources | ✅ done |
| S2-T07 | Track `playground/samples/` in git | ✅ done |

## Key Technical Decisions

- **SQLAlchemy 2.0 async** (`Mapped[]` annotations, `async_sessionmaker`, `aiosqlite` for local dev)
- **Repository pattern** — Protocol interfaces; `Sql*` for production, `InMemory*` for tests
- **LangGraph** — 4-node sequential pipeline (File Reception → Format Validation → Content Validation → Duplicate Control)
- **FastAPI + SSE** — `POST /pipeline/ingest` triggers background task; `GET /pipeline/{job_id}/events` streams node state
- **`dependency-injector`** — `DeclarativeContainer` + `@inject` + `Provide[Container.*]`; `TestContainer` swaps all `Sql*` repos with `InMemory*`
- **Document tracking** — `document_steps` records per-node path; `human_decisions` records reviewer actions; review queue via `GET /pipeline/review-queue`
- **Alembic async migrations** — `asyncio.run()` pattern in `env.py`; single connection string swap to move from SQLite to PostgreSQL

## Document Categories

The dataset covers 10 categories of municipal documents from Rosario's open-data portal:

| Category | Description | Documents |
|----------|-------------|-----------|
| `boletines` | Municipal bulletins | 2,035 |
| `compendios_de_boletines` | Bulletin compendiums | 27 |
| `convenios` | Agreements | 8 |
| `declaraciones_concejo_municipal` | Municipal council declarations | 37 |
| `decreto_ordenanzas` | Decree-ordinances | 344 |
| `decretos` | Decrees | 5,483 |
| `decretos_concejo_municipal` | Municipal council decrees | 6,738 |
| `ordenanzas` | Ordinances | 5,306 |
| `resoluciones` | Resolutions | 173 |
| `resoluciones_concejo_municipal` | Municipal council resolutions | 167 |
| **Total** | | **~20,318** |

Assuming ~200 KB average per PDF, that's **~4 GB** total storage. The ingested documents
(Phase 1 output) are available on [Google Drive](https://drive.google.com/drive/folders/1_IPfa4m1mmz6wFPOLtEf3T4xYknJap7B?usp=drive_link).

## Setup

```bash
uv sync --dev
```

Always use `uv sync` — do not use `pip install`.

## Models

The pipeline uses two models, neither of which is committed to git (see `.gitignore` —
everything under `models/` is ignored except a `.gitkeep` placeholder). A fresh clone
needs to fetch both before `node2`/`node3`/`node4` will work.

| Model | Purpose | Source | Target path |
|---|---|---|---|
| Phi-4-mini-instruct (Q4_K_M GGUF) | SLM used by node2 (format gray-zone) and node3 (content legitimacy) | [unsloth/Phi-4-mini-instruct-GGUF](https://huggingface.co/unsloth/Phi-4-mini-instruct-GGUF) | `models/Phi-4-mini-instruct-Q4_K_M.gguf` |
| all-MiniLM-L6-v2 | Embedding model used by node4 for semantic duplicate detection | [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | `models/embeddings/` (auto-downloaded on first use) |

**SLM — manual download required:**

```bash
uv run huggingface-cli download unsloth/Phi-4-mini-instruct-GGUF \
    Phi-4-mini-instruct-Q4_K_M.gguf --local-dir models
```

**Embedding model — no action needed.** `node4_duplicate_control.py`'s
`SentenceTransformer("all-MiniLM-L6-v2", cache_folder=Settings.embedding_model_path)`
downloads it automatically into `models/embeddings/` the first time node4 runs.

Both paths are configurable via `Settings` (`NODE2_MODEL_PATH`/`NODE3_MODEL_PATH` share
one path by default; `EMBEDDING_MODEL_PATH`) if you want to point at a different
location or a different quantization of the SLM.

## Development

```bash
uv run poe check   # lint + type check + coverage (run after every change)
uv run poe fmt     # auto-format
uv run poe test    # unit tests only
```

### Running the migrations

```bash
uv run alembic upgrade head   # apply all migrations to data/classiflow.db
uv run alembic downgrade -1   # roll back one revision
```

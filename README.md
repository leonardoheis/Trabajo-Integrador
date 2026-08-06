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

## Stage 1 — Ingesta Pipeline

Stage 1 is the first and only processing gate before a document enters the system.
It determines whether a file is **safe, valid, and new** — it never classifies content.
Accepted files are handed off to Stage 2 (text extraction + enrichment, future).

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
│   TEXT EXTRACTION   (Coordinator step — not a named node)        │
│                                                                  │
│   Attempt 1 — MarkItDown  (tables, columns, bad encodings)       │
│       ├─ chars ≥ min_chars (50) ─────────────────────────────► ✓ │
│       └─ chars < min_chars ──────────────────────────────────► OCR │
│                                                                  │
│   OCR path  (Stage 2 — not built yet)                            │
│       Attempt 2 — EasyOCR  (fast, CPU, clean scans)              │
│           ├─ chars ≥ min_usable (20) ──────────────────────────► ✓ │
│           └─ chars < min_usable ───────────────────────────────► REJECTED (unreadable) │
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
    ACCEPTED → Stage 2 (text extraction · enrichment · classification)
```

### Text extraction retry circuit

| Attempt | Tool | Trigger | Notes |
|---------|------|---------|-------|
| 1 | **MarkItDown** | always | Handles tables, columns, bad encodings, complex layouts. No model needed. |
| 2 | **EasyOCR** | `len(text) < 50` | Pixel-level OCR, CPU-only, good for clean scans. Fails job if `len(text) < 20`. |

MarkItDown runs inside the Stage 1 Coordinator (no model needed, fast).
EasyOCR runs in Stage 2 (heavier, separate process — not built yet).

### Routing outcomes

| Outcome | Meaning | Next step |
|---------|---------|-----------|
| `ACCEPTED` | All 4 nodes passed | Stage 2 pipeline |
| `REJECTED` | Hard failure at any node | Audit log, no retry |
| `REVIEW QUEUE` | Ambiguous result | Human reviewer decides |
| `REQUIRES_OCR` | Insufficient text from MarkItDown | Stage 2 EasyOCR path |

## Repository Structure

```
/
├── .claude/                        Claude Code project settings
├── documents/                      Reference documents and architecture diagrams
├── notebooks/                      Jupyter notebooks
│   └── colab_downloader.ipynb      Bulk download via Google Colab
├── scrapper/                       Phase 1 — ingestion scripts and CSV metadata
│   ├── downloader.py               Async bulk downloader
│   └── *.csv                       One CSV per document category (10 types)
├── src/
│   └── classiflow/                 Main Python package
│       ├── settings.py             pydantic-settings config (DATABASE_URL, JWT_*, etc.)
│       ├── shared/
│       │   ├── auth/
│       │   │   └── jwt.py          encode_token() / decode_token() / AuthError (PyJWT)
│       │   ├── audit/
│       │   │   └── service.py      AuditService — wraps IAuditRepository + loguru
│       │   ├── domain/
│       │   │   ├── job.py          NodeEvent, JobStatus
│       │   │   └── user.py         User, AuthToken
│       │   ├── events/
│       │   │   └── broadcaster.py  EventBroadcaster — asyncio.Queue per job_id
│       │   └── database/
│       │       ├── base.py         Async engine + session factory
│       │       ├── models.py       ORM models (6 tables)
│       │       └── repositories/   Protocol interfaces + SQL and InMemory impls
│       ├── ingesta/
│       │   ├── config.py           AllowedFormatsConfig — loads allowed_formats.yaml
│       │   ├── mime.py             MimeDetector callable — filetype-based MIME detection
│       │   ├── llm_provider.py     get_llm() / get_llm_langchain() singletons + MockLlm
│       │   ├── exceptions.py       LlmProviderError · ModelNotFoundError · ModelLoadError
│       │   ├── nodes/
│       │   │   ├── base.py                     BaseNode abstract class
│       │   │   ├── node1_file_reception.py      Size · SHA-256 · MIME detection
│       │   │   ├── node2_format_validation.py   Rule-based ACCEPT/REJECT/MANUAL_REVIEW + SLM
│       │   │   └── node3_content_validation.py  Length · language · legitimacy check
│       │   └── domain/
│       │       ├── results.py      FileReceptionResult, FormatValidationResult, etc.
│       │       └── state.py        JobState TypedDict (LangGraph coordinator state)
│       └── api/                    FastAPI application (in progress)
│           └── error_handlers/
│               ├── types.py        ExceptionHandler type + EXCEPTION_HANDLERS registry
│               └── llm.py          LlmErrorBody (Pydantic) + handlers for LLM errors
├── alembic/                        Database migrations
│   └── versions/
│       ├── 0001_initial_schema.py  Initial schema — all 6 tables
│       └── 0002_rename_agent_to_node.py  Rename agent columns to node
├── tasks/
│   ├── plan.md                     Full implementation plan
│   └── todo.md                     Task tracker
├── pyproject.toml                  Dependencies and tool configuration (managed by uv)
└── uv.lock                         Locked dependency graph
```

## Build Status

10 / 19 tasks complete · 1 skipped (T18 CI — deferred)

| Task | Description | Status |
|------|-------------|--------|
| T01 | Package skeleton + dependencies | ✅ done |
| T02 | Database models + Alembic migration | ✅ done |
| T03 | Repository implementations | ✅ done |
| T04 | JWT utilities | ✅ done |
| T07 | Shared domain + AuditService + EventBroadcaster | ✅ done |
| T08 | Ingesta domain models | ✅ done |
| T09 | Node 1 — File Reception | ✅ done |
| T10 | Node 2 — Format Validation (rule-based) | ✅ done |
| T11 | LLM Provider singleton | ✅ done |
| T12 | Node 2 — SLM escalation path | ✅ done |
| T13 | Node 3 — Content Validation | ✅ done |
| T05 | Google OAuth + whitelist | 🔲 pending |
| T06 | JWT auth middleware | 🔲 pending |
| T14 | Node 4 — Duplicate Control | 🔲 pending |
| T15 | Coordinator — LangGraph | 🔲 pending |
| T16 | FastAPI app + health route | 🔲 pending |
| T17 | Pipeline endpoints + SSE stream | 🔲 pending |
| T19 | Docker build + push | 🔲 pending |

Full task details and dependency graph: [tasks/todo.md](tasks/todo.md)

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

| Category | Description |
|----------|-------------|
| `boletines` | Municipal bulletins |
| `compendios_de_boletines` | Bulletin compendiums |
| `convenios` | Agreements |
| `declaraciones_concejo_municipal` | Municipal council declarations |
| `decreto_ordenanzas` | Decree-ordinances |
| `decretos` | Decrees |
| `decretos_concejo_municipal` | Municipal council decrees |
| `ordenanzas` | Ordinances |
| `resoluciones` | Resolutions |
| `resoluciones_concejo_municipal` | Municipal council resolutions |

The ingested documents (Phase 1 output) are available on [Google Drive](https://drive.google.com/drive/folders/1_IPfa4m1mmz6wFPOLtEf3T4xYknJap7B?usp=drive_link).

## Setup

```bash
uv sync --dev
```

Always use `uv sync` — do not use `pip install`.

## Running the Downloader (Phase 1)

```bash
uv run python scrapper/downloader.py --output ./downloads --concurrency 5 --delay 0.5
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--output` | `./downloads` | Destination folder for PDFs |
| `--concurrency` | `5` | Parallel downloads — keep ≤ 5 to avoid rate-limiting |
| `--delay` | `0.5` | Seconds between requests |

A `checkpoint.json` file tracks progress; re-running skips already-downloaded files.

Alternatively, open `notebooks/colab_downloader.ipynb` in Google Colab to run the downloader using cloud resources without any local setup.

## Development

```bash
uv run poe check   # lint + type check + notebook tests + coverage (run after every change)
uv run poe fmt     # auto-format
uv run poe test    # unit tests only
```

### Running the migrations

```bash
uv run alembic upgrade head   # apply all migrations to data/classiflow.db
uv run alembic downgrade -1   # roll back one revision
```

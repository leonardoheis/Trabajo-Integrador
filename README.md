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
│       ├── settings.py             pydantic-settings config (DATABASE_URL, etc.)
│       ├── shared/
│       │   └── database/
│       │       ├── base.py         Async engine + session factory
│       │       ├── models.py       ORM models (6 tables)
│       │       └── repositories/   Protocol interfaces + SQL and InMemory impls
│       ├── ingesta/                Ingestion agents (in progress)
│       └── api/                    FastAPI application (in progress)
├── alembic/                        Database migrations
│   └── versions/
│       └── 0001_initial_schema.py  Initial schema — all 6 tables
├── tasks/
│   ├── plan.md                     Full implementation plan
│   └── todo.md                     Task tracker
├── pyproject.toml                  Dependencies and tool configuration (managed by uv)
└── uv.lock                         Locked dependency graph
```

## Build Status

| Task | Description | Status |
|------|-------------|--------|
| T01 | Package skeleton + dependencies | ✅ done |
| T02 | Database models + Alembic migration | ✅ done |
| T03 | Repository implementations | ✅ done |
| T04 | JWT utilities | 🔲 pending |
| T07 | Shared domain + AuditService + EventBroadcaster | 🔲 pending |
| T05 | Google OAuth + whitelist | 🔲 pending |
| T08 | Ingesta domain models | 🔲 pending |
| T06 | JWT auth middleware | 🔲 pending |
| T09–T14 | Ingestion agents | 🔲 pending |
| T15 | Coordinator — LangGraph | 🔲 pending |
| T16 | FastAPI app + health route | 🔲 pending |
| T17 | Pipeline endpoints + SSE stream | 🔲 pending |

Full task details and dependency graph: [tasks/todo.md](tasks/todo.md)

## Key Technical Decisions

- **SQLAlchemy 2.0 async** (`Mapped[]` annotations, `async_sessionmaker`, `aiosqlite` for local dev)
- **Repository pattern** — Protocol interfaces; `Sql*` for production, `InMemory*` for tests
- **LangGraph** — 4-agent sequential pipeline (File Reception → Format Validation → Content Validation → Duplicate Control)
- **FastAPI + SSE** — `POST /pipeline/ingest` triggers background task; `GET /pipeline/{job_id}/events` streams agent state
- **`dependency-injector`** — `DeclarativeContainer` + `@inject` + `Provide[Container.*]`; `TestContainer` swaps all `Sql*` repos with `InMemory*`
- **Document tracking** — `document_steps` records per-agent path; `human_decisions` records reviewer actions; review queue via `GET /pipeline/review-queue`
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
uv run alembic upgrade head   # apply all migrations to classiflow.db
uv run alembic downgrade -1   # roll back one revision
```

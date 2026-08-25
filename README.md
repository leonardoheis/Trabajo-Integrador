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

## Stages

| Stage | Scope | Status |
|---|---|---|
| 1 | Ingesta pipeline — reception, format/content validation, duplicate control | ✅ done — [PR #17](https://github.com/leonardoheis/Trabajo-Integrador/pull/17) |
| 2 | Extraction hardening — bounded concurrency + observability around Stage 1's text extraction | ✅ done — [PR #20](https://github.com/leonardoheis/Trabajo-Integrador/pull/20) |
| 3 | Refinement & enrichment — text cleaning, entity extraction, metadata enrichment | ✅ done — [PR #21](https://github.com/leonardoheis/Trabajo-Integrador/pull/21) |
| 4 | Classification & routing — primary classifier, BETO v2 second opinion, LLM judge, review queue | ✅ done — [PR #22](https://github.com/leonardoheis/Trabajo-Integrador/pull/22) |
| 5 | Knowledge base + chat agent | 🔲 not started — see [`tasks/plan_stage5.md`](tasks/plan_stage5.md) |

Full task-by-task detail per stage: [`tasks/todo_stage2.md`](tasks/todo_stage2.md) ·
[`tasks/todo_stage3.md`](tasks/todo_stage3.md) · [`tasks/todo_stage4.md`](tasks/todo_stage4.md).

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
│             │  · gray zone → SLM decides (shared Meta-Llama-3.1-8B-Instruct)
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
│             │  · SLM legitimacy check (shared Meta-Llama-3.1-8B-Instruct)
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
├── config/                         YAML config, one file per pipeline stage/concern
│   ├── allowed_formats.yaml · content_validation.yaml
│   ├── duplicate_control.yaml · extraction.yaml
│   └── enrichment.yaml · classification.yaml
├── models/                         SLM/LLM + embedding model weights (see "Models" below —
│                                   bert_tunning_beto_v2/ committed via Git LFS, rest gitignored)
├── src/
│   └── classiflow/                 Main Python package
│       ├── settings.py             pydantic-settings config (DATABASE_URL, JWT_*, model paths, etc.)
│       ├── domain/                 job.py (NodeEvent, JobStatus) · user.py (User, AuthToken) ·
│       │                           base.py (BaseEntity) · repositories/ (Protocol interfaces)
│       ├── database/                base.py (async engine/session) · models.py (ORM, 8 tables) ·
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
│       ├── enrichment/              Stage 3 — text cleaning + entity/metadata enrichment
│       │   ├── coordinator.py       build_enrichment_coordinator() — LangGraph state machine
│       │   ├── nodes/               text_cleaner.py · entity_extractor.py · metadata_enricher.py
│       │   ├── domain/              EnrichedRecord and related result types
│       │   └── prompts/             entity_extraction.py — LLM chain builder
│       ├── classification/          Stage 4 — classification, second opinion, routing
│       │   ├── coordinator.py       build_classification_coordinator() — LangGraph state machine
│       │   ├── bert/                BETO v2 second-opinion classifier, SVM reviewer, OOD scorer
│       │   ├── nodes/               primary_classifier · second_opinion · foreign_municipality ·
│       │   │                       smells_risk · confidence_gate · llm_judge · routing
│       │   ├── domain/              DocumentCategory · ReviewRoute · results
│       │   └── prompts/             primary_classification.py · llm_judge.py
│       ├── pipeline/                base.py (BaseNode) · context.py (JobContext) — shared across stages
│       ├── storage/                 document_storage.py — classified-document filesystem layout
│       ├── api/                    FastAPI application
│       │   ├── app.py · runner.py · dependencies.py (DI-wired Depends() aliases)
│       │   ├── routes/             auth/ · health/ · pipeline/ (ingest, SSE events, review queue) ·
│       │   │                       classification/ (review-queue decisions)
│       │   └── error_handlers/     typed exception → JSONResponse handlers
│       ├── injections/             production.py (Container) · test.py (TestContainer)
│       └── playground/             stage1/ · stage2/ · stage3/ · stage4/ demo notebooks ·
│                                   samples/ (sample PDFs the notebooks depend on)
├── alembic/versions/                0001 initial schema · 0002 rename agent→node ·
│                                   0003 add Job.extracted_text · 0004 enriched_records ·
│                                   0005 classification_records · 0006 judge verdict fields ·
│                                   0007 enriched_record raw_text
├── tasks/                          plan_stageN.md + todo_stageN.md per stage (1–5)
├── pyproject.toml                  Dependencies and tool configuration (managed by uv)
└── uv.lock                         Locked dependency graph
```

## Stage 3 — Refinement & Enrichment (done — merged via [PR #21](https://github.com/leonardoheis/Trabajo-Integrador/pull/21))

Runs automatically after a job is `ACCEPTED` by Stage 1. Cleans the raw extracted text
and enriches it with structured metadata ahead of classification:

- **Text cleaner** (`enrichment/nodes/text_cleaner.py`) — NFC normalization, gibberish-line
  detection, table-border/whitespace fixes. Produces `cleaned_text`; the pre-cleaning
  `raw_text` is also persisted on `EnrichedRecord` for future embedding use.
- **Entity extractor** (`entity_extractor.py`) — LLM chain pulling structured entities
  (dates, ordinance numbers, named parties) out of `cleaned_text`.
- **Metadata enricher** (`metadata_enricher.py`) — attaches derived metadata to the
  `EnrichedRecord` persisted for Stage 4.

## Stage 4 — Classification & Routing (done — merged via [PR #22](https://github.com/leonardoheis/Trabajo-Integrador/pull/22))

A LangGraph pipeline (`classification/coordinator.py`) that classifies each
`EnrichedRecord`, cross-checks the result, and routes it to auto-accept, an LLM judge,
or a human reviewer:

```
primary_classifier ──► second_opinion ──► foreign_municipality ──► smells_risk ──► confidence_gate
                                                                                        │
                                                    ┌───────────────────────────────────┤
                                                    ▼                                   ▼
                                                llm_judge                           routing
                                                    │                                   ▲
                                                    └───────────────────────────────────┘
```

- **Primary classifier** (LLM, shared Llama 3.1 8B) — assigns one of 11
  `DocumentCategory` labels + confidence + `all_scores`.
- **Second opinion** (BETO v2, `classification/bert/`) — a fine-tuned Spanish BERT
  classifier + SVM reviewer, with out-of-distribution (OOD) scoring (Mahalanobis /
  cosine / kNN) to gauge how much to trust its own disagreement.
- **Foreign municipality detector** — flags text naming an issuing body other than
  Municipalidad de Rosario.
- **Smells + risk score** — heuristic caution flags (not a verdict) surfaced to the judge.
- **Confidence gate** (`nodes/confidence_gate.py`) — pure routing logic: `foreign_municipality`
  or a primary label of `otro` always force `human_review`; a primary/second-opinion
  disagreement or low confidence routes to the LLM judge; otherwise auto-`accept`.
- **LLM judge** (Gemma 4) — final quality gate for judge-routed cases; weighs the second
  opinion's OOD/SVM grounding and returns `final_label` + `reasoning`, but a genuine
  disagreement never auto-accepts regardless of its verdict.
- **Routing** — persists the `ClassificationRecord` (including judge verdict fields) and
  writes the audit log entry.

Human-reviewed jobs are corrected via `POST /classification/{job_id}/decision`, which
upserts the existing record rather than duplicating it.

## Build Status

Stage 1–4 status, task tables, and PR links are summarized in the [Stages](#stages)
table above. Full per-task detail: [`tasks/todo.md`](tasks/todo.md) (Stage 1) ·
[`tasks/todo_stage2.md`](tasks/todo_stage2.md) · [`tasks/todo_stage3.md`](tasks/todo_stage3.md) ·
[`tasks/todo_stage4.md`](tasks/todo_stage4.md).

## Key Technical Decisions

- **SQLAlchemy 2.0 async** (`Mapped[]` annotations, `async_sessionmaker`, `aiosqlite` for local dev)
- **Repository pattern** — Protocol interfaces; `Sql*` for production, `InMemory*` for tests
- **LangGraph** — one coordinator per stage: Stage 1's 4-node ingesta pipeline (File
  Reception → Format Validation → Content Validation → Duplicate Control), plus
  dedicated Stage 3 (enrichment) and Stage 4 (classification & routing) coordinators
- **FastAPI + SSE** — `POST /pipeline/ingest` triggers background task; `GET /pipeline/{job_id}/events` streams node state
- **`dependency-injector`** — `DeclarativeContainer` + `@inject` + `Provide[Container.*]`; `TestContainer` swaps all `Sql*` repos with `InMemory*`
- **Document tracking** — `document_steps` records per-node path; `human_decisions` records reviewer actions; review queue via `GET /pipeline/review-queue`
- **Alembic async migrations** — `asyncio.run()` pattern in `env.py`; single connection string swap to move from SQLite to PostgreSQL
- **BETO v2 second opinion** — a fine-tuned Spanish BERT classifier + SVM reviewer + OOD
  scoring (Mahalanobis / cosine / kNN), used to cross-check the primary LLM classifier
  without duplicating its cost on every job
- **LLM judge as disagreement arbiter** — a separate model (Gemma 4) resolves
  primary/second-opinion disagreements using the second opinion's own OOD/SVM grounding,
  but never auto-accepts a genuine disagreement regardless of its verdict

## Document Categories

The dataset covers 10 categories of municipal documents from Rosario's open-data portal,
plus an 11th (`otro`) added to give the primary classifier an escape hatch for documents
that aren't from Municipalidad de Rosario at all — closing a gap where such documents
could otherwise get silently auto-accepted under the wrong municipal label. BETO v2 (the
second-opinion agent) was only trained on 9 of these — `compendios_de_boletines` and
`convenios` are LLM-only labels.

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
| `otro` | Not a Municipalidad de Rosario document | — |
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

The pipeline uses four models. `models/bert_tunning_beto_v2/` is committed via Git LFS
(clone as normal — no separate download step). Everything else under `models/` is
gitignored and must be fetched manually before the pipeline will run end to end.

| Model | Purpose | Source | Target path |
|---|---|---|---|
| Meta-Llama-3.1-8B-Instruct (Q4_K_M GGUF) | Shared SLM/LLM for node2 (format gray-zone), node3 (content legitimacy), Stage 3 enrichment, and the Stage 4 primary classifier | Hugging Face — search for a Q4_K_M GGUF quantization of `Meta-Llama-3.1-8B-Instruct` | `models/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf` |
| Gemma 4 E4B-it (Q4_K_M GGUF) | LLM judge — final quality gate for judge-routed classification cases | Hugging Face — search for a Q4_K_M GGUF quantization of `gemma-4-E4B-it` | `models/gemma-4-E4B-it-Q4_K_M.gguf` |
| BETO v2 (fine-tuned) | Stage 4 second-opinion classifier + SVM reviewer + OOD scoring | committed via Git LFS | `models/bert_tunning_beto_v2/` |
| all-MiniLM-L6-v2 | Embedding model used by node4 for semantic duplicate detection | [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | `models/embeddings/` (auto-downloaded on first use) |

**LLM/SLM — manual download required.** Find a Q4_K_M GGUF release for each model on
Hugging Face (e.g. via the Hub search UI or `huggingface-cli search`), then:

```bash
uv run huggingface-cli download <repo-id> \
    Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf --local-dir models
uv run huggingface-cli download <repo-id> \
    gemma-4-E4B-it-Q4_K_M.gguf --local-dir models
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

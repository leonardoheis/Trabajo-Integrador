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
| 5 | Knowledge base + chat agent | ✅ done — [PR #25](https://github.com/leonardoheis/Trabajo-Integrador/pull/25), [PR #26](https://github.com/leonardoheis/Trabajo-Integrador/pull/26), [PR #27](https://github.com/leonardoheis/Trabajo-Integrador/pull/27), [PR #28](https://github.com/leonardoheis/Trabajo-Integrador/pull/28), [PR #29](https://github.com/leonardoheis/Trabajo-Integrador/pull/29), [PR #30](https://github.com/leonardoheis/Trabajo-Integrador/pull/30) |

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
│       ├── knowledge/                Stage 5 — RAG knowledge base + chat, one folder per pipeline
│       │   │                       stage: domain/ · chunking/ · embeddings/ · vectordb/ ·
│       │   │                       retrieval/ · prompts/ · llm/ · chat/ · indexing/ · memory/
│       │   │                       (conversation history + summarization)
│       ├── model_cache.py           evict_lru_cache() — shared VRAM-eviction helper for every
│       │                           cached model loader (SLM, BERT, chat LLM, both embedders)
│       ├── pipeline/                base.py (BaseNode) · context.py (JobContext) — shared across stages
│       ├── storage/                 document_storage.py — classified-document filesystem layout
│       ├── api/                    FastAPI application
│       │   ├── app.py · runner.py · dependencies.py (DI-wired Depends() aliases)
│       │   ├── routes/             auth/ · health/ · pipeline/ (ingest, SSE events, review queue) ·
│       │   │                       classification/ (review-queue decisions) ·
│       │   │                       knowledge/ (chat, sync, per-document indexing)
│       │   └── error_handlers/     typed exception → JSONResponse handlers
│       ├── injections/             production.py (Container) · test.py (TestContainer)
│       ├── frontend/                React 19 + Vite + Tailwind v4 web UI — Processing,
│       │                           Classification, Document Detail, Users, Audit Log, Chat pages
│       └── playground/             stage1/ · stage2/ · stage3/ · stage4/ · stage5/ demo notebooks ·
│                                   samples/ (sample PDFs the notebooks depend on)
├── alembic/versions/                0001 initial schema · 0002 rename agent→node ·
│                                   0003 add Job.extracted_text · 0004 enriched_records ·
│                                   0005 classification_records · 0006 judge verdict fields ·
│                                   0007 enriched_record raw_text · 0008 allowed_user is_admin ·
│                                   0009 documents catalogue · 0010 rename documents→document_kb ·
│                                   0011 enriched_record filename/sha256 · 0012 drop
│                                   scraped-catalogue-only columns from document_kb ·
│                                   0013 add conversation_turns/conversation_summaries
├── tasks/                          plan_stageN.md + todo_stageN.md per stage (1–5)
├── docs/superpowers/                specs/ + plans/ — design specs and implementation plans
│                                   for work done via the superpowers brainstorming/planning flow
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

## Stage 5 — Knowledge Base + Chat Agent (done — [PR #25](https://github.com/leonardoheis/Trabajo-Integrador/pull/25), [PR #26](https://github.com/leonardoheis/Trabajo-Integrador/pull/26), [PR #27](https://github.com/leonardoheis/Trabajo-Integrador/pull/27), [PR #28](https://github.com/leonardoheis/Trabajo-Integrador/pull/28), [PR #29](https://github.com/leonardoheis/Trabajo-Integrador/pull/29), [PR #30](https://github.com/leonardoheis/Trabajo-Integrador/pull/30))

A RAG (retrieval-augmented generation) pipeline (`src/classiflow/knowledge/`) that indexes
accepted, classified documents and answers questions about them with cited sources:

```
EnrichedRecord (accepted) ──► chunk ──► embed ──► ChromaDB
                                                      │
question ──► embed ──► similarity search ◄───────────┘
                │
          top-k chunks ──► chat prompt ──► local LLM (llama.cpp) ──► streamed answer + sources
```

- **Indexing is manual, never automatic.** A document only enters the Knowledge Base when a
  human (or an accepted auto-classification) explicitly triggers it — the "Index into
  Knowledge Base" button on a document's detail page, or the "Sync Knowledge Base" batch
  action on the Classification page (`PipelineService.synchronize_kb()`). Only `accept`-routed
  documents are eligible; classification alone never indexes anything.
- **Chunking** (`knowledge/chunking/`) splits `cleaned_text` into overlapping windows
  (`CHUNK_SIZE`/`CHUNK_OVERLAP`), each headed with a citation line derived from the document's
  own extracted entities (`doc_type`/`number`/`year`) — no external metadata source (an earlier
  CSV-based lookup was dropped in favor of the LLM-extracted entities already produced during
  enrichment).
- **Embeddings** — a multilingual SentenceTransformer (`paraphrase-multilingual-MiniLM-L12-v2`,
  separate from node4's `all-MiniLM-L6-v2` duplicate-control model, which must not change since
  its threshold is calibrated against it) — see **Models** below for the manual download step.
- **Retrieval** (`knowledge/retrieval/`) does similarity search over Chroma, with an automatic
  fallback: if a question names a document by filename, that filename is used as an exact
  metadata filter instead of relying purely on embedding similarity (dense search is weak at
  exact identifier lookup).
- **Chat** (`knowledge/chat/`) streams a local llama.cpp completion (`Meta-Llama-3.1-8B-Instruct`,
  the same model file the ingestion/classification stages share) grounded strictly in the
  retrieved passages, with inline source citations. Streaming is real token-by-token generation
  (a background thread bridges llama.cpp's blocking `stream=True` generator to the async caller
  via a queue), not a single buffered chunk.
- **Conversation memory** (`knowledge/memory/`) persists each user's chat history across sessions
  in `conversation_turns`/`conversation_summaries`. Every new question includes the last 6 turns
  verbatim plus a running summary of older ones; once a 7th turn is saved, the oldest turn folds
  into that summary via one extra LLM call, fired after the answer has already streamed back so it
  never adds latency to a response. `GET`/`DELETE /knowledge/conversation` expose the full history
  and a "Clear conversation" reset; raw turns are never auto-pruned.
- **VRAM isolation** — the chat model, the pipeline's own SLM/BERT models, and both embedding
  models are evicted from GPU memory at the start and end of every pipeline job (`model_cache.py`'s
  `evict_lru_cache()`), so a chat session and a processing job never hold two resident copies at
  once on the same card. The chat model is pre-warmed when the Chat page opens, skipped silently
  if a job is currently running, and also released on sign-out (`POST /auth/logout`) so it doesn't
  sit resident indefinitely after a session ends. Unloading skips itself (rather than blocking)
  while a chat generation is actively in flight, since llama.cpp's C bindings aren't safe for
  concurrent use of one model handle from two threads.
- **Frontend** (`src/classiflow/frontend/`, React + Vite + Tailwind) — a Chat page with streamed,
  markdown-rendered answers and source citations, prior-conversation history loaded on mount, a
  Knowledge Base tab on the document detail page, and an "Indexed" column on the Classification
  table showing which documents are actually in the KB. Beyond the chat surface:
  - **Classification search** — one box filters on label *or* filename (`GET /jobs?search=`),
    alongside the sortable columns and page-size control.
  - **Find in text** — a Ctrl+F-style bar on the document detail page's Extraction tab:
    highlight-all with an active-match accent, `n of m` counter, ↑/↓ buttons and
    Enter/Shift+Enter to step through matches, which scroll into view as they become active.
  - **Review Queue page** — the `human_review`/`escalate` backlog with its per-document step
    timeline, split out from the Classification table.
  - **Reopen a review decision** (admin only) — a reviewer who files a document under the wrong
    label used to have no way back: the decision endpoint refuses a second decision, and the
    document is already filed and indexed. `POST /classification/{job_id}/reopen` returns it to
    the queue, gated on `allowed_users.is_admin` and requiring a written reason that lands in
    the audit log. The label is deliberately *not* reverted — records predating
    `original_label` have no machine prediction to revert to, so the operation would otherwise
    behave differently depending on when the record was created.
  - **PDF first/last page** — `« First` and `Last »` beside Prev/Next, shown only on
    multi-page documents. Signature pages are usually last, and stepping there one page at a
    time was the common case.
  - **Job control** — queued or failed jobs can be discarded from the Processing page
    (`DELETE /pipeline/jobs/{job_id}`); jobs mid-flight are refused.
  - **Page-scoped model warmup** — navigating to Processing or Classification calls
    `POST /pipeline/warmup` (releasing the chat GGUF), and opening Chat calls
    `POST /knowledge/chat/warmup` (releasing the pipeline's models first). Both no-op while a
    job is running.
  - **Metrics page** (`/metrics`) — strict vs. safeguarded accuracy, per-category
    precision/recall/F1, a confusion matrix, and the list of wrong labels that reached
    storage without review. Served by `GET /classification/metrics`.
  - **Light/dark theme toggle** and a reworked collapsible sidebar with Google profile pictures.

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
- **Per-request DB sessions for auth** — `get_current_user` builds its repo from FastAPI's own
  `Depends(get_session)`, never from the container's process-wide `Resource`. Two concurrent
  requests sharing one `AsyncSession` raise SQLAlchemy's "session is provisioning a new
  connection" error, which any page issuing parallel queries will hit.
- **stdout/stderr re-opened in the API subprocess** — W&B's console capture wraps the parent
  process's streams, and the spawned uvicorn worker inherits handles that are invalid there
  (`OSError: [WinError 1]` on every write). `create_app()` drops loguru's default sink and
  re-adds one over a duplicated fd with `errors="replace"`; `runner.py` does the same for
  `sys.stdout`/`sys.stderr`, which uvicorn's stdlib access logger re-reads at emit time.
- **Alembic async migrations** — `asyncio.run()` pattern in `env.py`; single connection string swap to move from SQLite to PostgreSQL
- **BETO v2 second opinion** — a fine-tuned Spanish BERT classifier + SVM reviewer + OOD
  scoring (Mahalanobis / cosine / kNN), used to cross-check the primary LLM classifier
  without duplicating its cost on every job
- **LLM judge as disagreement arbiter** — a separate model (Gemma 4) resolves
  primary/second-opinion disagreements using the second opinion's own OOD/SVM grounding,
  but never auto-accepts a genuine disagreement regardless of its verdict
- **Weave (W&B) tracing** — every pipeline node is wrapped in `weave.op()` at class-definition
  time (`pipeline/base.py`); tracing only activates when `WANDB_API_KEY` is set, so a clone
  with no `.env` (including every test run) never calls `weave.init()` or reaches the network
- **Explicit, never-automatic Knowledge Base indexing** — a document enters the KB only via a
  manual action (per-document button or batch sync), never as a side effect of classification,
  and its cached models (chat LLM, both embedders) are evicted from VRAM at every pipeline job
  boundary so a chat session and a processing job never both hold a model resident at once
- **Chat memory as a bounded window + running summary, not unbounded history** — the last 6 turns
  are sent verbatim on every question; older turns are folded into a single running summary via
  one extra LLM call, deliberately fired *after* the current answer has streamed back so memory
  bookkeeping never adds latency to a user-visible response

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
npm --prefix src/classiflow/frontend install   # frontend dependencies
```

Always use `uv sync` — do not use `pip install`.

## Models

The pipeline uses five models. `models/bert_tunning_beto_v2/` is committed via Git LFS
(clone as normal — no separate download step). Everything else under `models/` is
gitignored and must be fetched manually before the pipeline will run end to end — **every
model here loads with `local_files_only=True`, so nothing is ever fetched at request time,
including the two embedding models below** (this changed from an earlier auto-download
behavior; both must now be present on disk before first use).

| Model | Purpose | Source | Target path |
|---|---|---|---|
| Meta-Llama-3.1-8B-Instruct (Q4_K_M GGUF) | Shared SLM/LLM for node2 (format gray-zone), node3 (content legitimacy), Stage 3 enrichment, the Stage 4 primary classifier, and the Stage 5 chat agent | Hugging Face — search for a Q4_K_M GGUF quantization of `Meta-Llama-3.1-8B-Instruct` | `models/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf` |
| Gemma 4 E4B-it (Q4_K_M GGUF) | LLM judge — final quality gate for judge-routed classification cases | Hugging Face — search for a Q4_K_M GGUF quantization of `gemma-4-E4B-it` | `models/gemma-4-E4B-it-Q4_K_M.gguf` |
| BETO v2 (fine-tuned) | Stage 4 second-opinion classifier + SVM reviewer + OOD scoring | committed via Git LFS | `models/bert_tunning_beto_v2/` |
| all-MiniLM-L6-v2 | Embedding model used by node4 for semantic duplicate detection | [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | `models/embeddings/` |
| paraphrase-multilingual-MiniLM-L12-v2 | Stage 5 chat/indexing embedder (multilingual — the corpus is Spanish); kept separate from node4's model since node4's duplicate-detection threshold is calibrated against that specific model and must not move | [sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) | default HF cache (or `EMBEDDING_MODEL_PATH` if set) |

**LLM/SLM — manual download required.** Find a Q4_K_M GGUF release for each model on
Hugging Face (e.g. via the Hub search UI or `huggingface-cli search`), then:

```bash
uv run huggingface-cli download <repo-id> \
    Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf --local-dir models
uv run huggingface-cli download <repo-id> \
    gemma-4-E4B-it-Q4_K_M.gguf --local-dir models
```

**Embedding models — manual download required too.** Both are pinned by name via
`sentence_transformers.SentenceTransformer(..., local_files_only=True)`, so they must already
be present in the local cache before first use:

```bash
uv run huggingface-cli download sentence-transformers/all-MiniLM-L6-v2 \
    --local-dir models/embeddings/models--sentence-transformers--all-MiniLM-L6-v2
uv run huggingface-cli download sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

(The second command uses the default Hugging Face cache location, matching what
`SentenceTransformer` looks for when no `cache_folder` is given — set `HF_HOME` first if you
want it somewhere else.)

Both GGUF paths are configurable via `Settings` (`NODE2_MODEL_PATH`/`NODE3_MODEL_PATH` share
one path by default; `EMBEDDING_MODEL_PATH` for node4's embedder) if you want to point at a
different location or a different quantization.

## Development

```bash
uv run poe check   # lint + typecheck + full test suite + full pre-commit (run after every change)
uv run poe fmt     # auto-format
uv run poe test    # unit tests only, no coverage report
uv run poe serve   # backend + frontend together (python -m classiflow)
```

Backend and frontend can also run separately:

```bash
uv run poe serve-api   # uvicorn, port 8000 (no --reload -- see note below)
uv run poe serve-ui    # vite dev server (src/classiflow/frontend)
```

`--reload` is intentionally not used: its reloader-parent/worker-subprocess split made an
already-hung backend (see below) much harder to stop cleanly. Restart manually after backend
code changes.

Every backend run also writes `classiflow.log` at the repo root, overwritten fresh on each
start — useful for finding exactly where a stuck job's execution stopped without needing to
scroll back through terminal output.

### Running the migrations

```bash
uv run alembic upgrade head   # apply all migrations to data/classiflow.db
uv run alembic downgrade -1   # roll back one revision
```

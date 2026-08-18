# Stage 3: Refinement & Enrichment

## Responsibility

Takes the extracted text from the `"extraction"` `DocumentStep` (Stage 2 output — see
`plan_stage2.md` S2-T04) and produces an `EnrichedRecord` ready for classification —
and, critically, `EnrichedRecord.cleaned_text` is the exact text Stage 5 (RAG
embeddings) will chunk and embed. A document with no `EnrichedRecord` is a document
invisible to RAG, which is why this stage's failure behavior is a first-class design
concern, not an afterthought. Three sequential steps: **clean → extract entities →
enrich metadata**.

Full architectural design (package layout, LLM chain shape, text-cleaning algorithm,
trigger wiring, failure handling) is in
`docs/superpowers/specs/2026-08-17-refinement-enrichment-design.md` — this file keeps
the settled field lists and DB model shape; that spec is the source of truth for *how*.

Note: an earlier draft of this stage had Stage 2 write a dedicated `ExtractionRecord`
table and referenced it here as this stage's input. Stage 2 was redefined to reuse the
existing `DocumentStep` table instead (see `plan_stage2.md`'s Architecture Decisions) —
`ExtractionRecord` was never built. Read `extracted text` below as "the `text` field in
the `"extraction"` step's `DocumentStep.detail` for this job," not a separate table.

## Steps

### 1. Text Cleaning

- Strip repeated headers/footers — **not** literal "detect lines repeated across
  pages" (rejected: neither extractor preserves page boundaries in its output, see the
  design doc). Uses frequency-based repeated-line detection instead: any line appearing
  3+ times (configurable) across the whole document is treated as a running
  header/footer, regardless of which page produced it.
- Remove page numbers and section separators
- Remove OCR artifacts (spurious characters, line-break noise)
- Normalize Unicode (accents and ligatures common in municipal PDF scans)
- Output: `cleaned_text: str`

### 2. Entity Extraction (LLM chain)

Extract structured fields from `cleaned_text`. All fields optional — return what is found.

| Field | Type | Example |
|---|---|---|
| `doc_type_hint` | str\|None | `"ordenanza"`, `"decreto"`, `"resolucion"` |
| `number` | str\|None | `"6801"` |
| `year` | int\|None | `1999` |
| `issuing_body` | str\|None | `"Concejo Municipal"` |
| `signatories` | list[str] | `["Hermes Binner"]` |
| `article_count` | int\|None | number of `ARTÍCULO` entries detected |

### 3. Metadata Enrichment

Attach context from outside the document body:

| Field | Source |
|---|---|
| `source` | Hardcoded `"manual_upload"` — the only live ingestion path since the `scrapper/` directory was deleted (no source produces `"municipal_dataset"`/`"web_scraping"` documents anymore). `csv_category` is dropped entirely for the same reason. |
| `filename` | original filename |
| `language` | from Stage 1 Node 3 (already detected, not re-detected) |
| `sha256` | from Stage 1 Node 1 (`FileReceptionResult.sha256`, already computed) |
| `stage2_extractor_used` | from the `"extraction"` `DocumentStep.detail` |

## DB Model — EnrichedRecord

| Field | Type | Notes |
|---|---|---|
| `id` | int | PK (autoincrement) |
| `job_id` | str | FK → `Job` (same key `DocumentStep` already uses) |
| `cleaned_text` | str | |
| `entities` | JSON | EntityExtraction fields above |
| `metadata` | JSON | enrichment fields above |
| `created_at` | datetime | |

## Tasks

See `todo_stage3.md` for the full task list and parallel execution map.

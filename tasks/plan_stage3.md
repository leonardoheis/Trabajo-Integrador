# Stage 3: Refinement & Enrichment

## Responsibility

Takes the extracted text from the `"extraction"` `DocumentStep` (Stage 2 output — see
`plan_stage2.md` S2-T04) and produces an `EnrichedRecord` ready for classification.
Three sequential steps: **clean → extract entities → enrich metadata**.

Note: an earlier draft of this stage had Stage 2 write a dedicated `ExtractionRecord`
table and referenced it here as this stage's input. Stage 2 was redefined to reuse the
existing `DocumentStep` table instead (see `plan_stage2.md`'s Architecture Decisions) —
`ExtractionRecord` was never built. Read `extracted text` below as "the `text` field in
the `"extraction"` step's `DocumentStep.detail` for this job," not a separate table.

## Steps

### 1. Text Cleaning

- Strip repeated headers/footers (heuristic: detect lines repeated across pages)
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
| `source` | `"municipal_dataset"` \| `"web_scraping"` \| `"manual_upload"` |
| `csv_category` | original CSV category from the scraper (if applicable) |
| `filename` | original filename |
| `language` | from Stage 1 Node 3 (already detected, not re-detected) |
| `sha256` | from Stage 1 Node 4 (already computed) |
| `stage2_extractor_used` | from the `"extraction"` `DocumentStep.detail` |

## DB Model — EnrichedRecord

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `job_id` | str | FK → `Job` (same key `DocumentStep` already uses) |
| `cleaned_text` | str | |
| `entities` | JSON | EntityExtraction fields above |
| `metadata` | JSON | enrichment fields above |
| `created_at` | datetime | |

## Tasks

See `todo_stage3.md` for the full task list and parallel execution map.

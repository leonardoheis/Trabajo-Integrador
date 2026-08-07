# Stage 3: Refinement & Enrichment

## Responsibility

Takes an `ExtractionRecord` (Stage 2 output) and produces an `EnrichedRecord` ready for
classification. Three sequential steps: **clean → extract entities → enrich metadata**.

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
| `stage2_extractor_used` | from ExtractionRecord |

## DB Model — EnrichedRecord

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `file_id` | UUID | FK → ingested file |
| `extraction_id` | UUID | FK → ExtractionRecord |
| `cleaned_text` | str | |
| `entities` | JSON | EntityExtraction fields above |
| `metadata` | JSON | enrichment fields above |
| `created_at` | datetime | |

## Tasks

See `todo_stage3.md` for the full task list and parallel execution map.

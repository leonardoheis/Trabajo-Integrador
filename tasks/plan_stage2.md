# Stage 2: Text Extraction

## Responsibility

Takes accepted files from Stage 1 and extracts usable text. Runs as a separate async
pipeline, triggered when Stage 1 marks a file as accepted. Writes an `ExtractionRecord`
to the DB (always-on) and emits SSE events through `EventBroadcaster`.

## Architecture

```
Stage 1 → accepted file record in DB
        │
        ▼
asyncio.Queue  (in-process, bounded by max_concurrent_extractions)
        │
        ├── Worker 1 ──► MarkItDown → PaddleOCR fallback
        ├── Worker 2 ──► MarkItDown → PaddleOCR fallback
        └── Worker N ──► …
        │
        ▼
ExtractionRecord written to DB  (always, success or failure)
        │
        ▼
SSE events ──► EventBroadcaster ──► frontend
```

## Extraction Chain

Pattern adapted from bert_tunning `src/ingestion/extract.py`:

1. Try **MarkItDown** — if `len(text) >= min_text_for_ocr` → done.
2. If below threshold → try **PaddleOCR**.
3. All extractors failed → `status="failed"`, error recorded.
4. If `len(text) < min_usable_text` after all extractors → `status="unreadable"`, `text=None`.
5. Otherwise → `status="done"`, `extractor_used`, `char_count` stored.

## Config (`config/extraction.yaml`)

```yaml
max_concurrent_extractions: 2   # ponytail: move to config page when UI admin exists
min_text_for_ocr: 50            # chars; below this MarkItDown triggers OCR fallback
min_usable_text: 20             # chars; below this text is unusable even after OCR
verbose_events: false           # gate extra SSE events (per-page OCR progress, etc.)
```

## SSE Events

| Event | Payload | When |
|---|---|---|
| `extraction_queued` | `file_id`, `queue_position`, `queue_size` | File enters queue |
| `extraction_started` | `file_id`, `queue_position` | Worker picks up file |
| `ocr_started` | `file_id` | MarkItDown yield < `min_text_for_ocr` |
| `extraction_done` | `file_id`, `extractor_used`, `char_count` | Success |
| `extraction_failed` | `file_id`, `reason` | All extractors failed |

When `verbose_events: true`: per-page OCR progress, intermediate char counts.

## DB Model — ExtractionRecord

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `file_id` | UUID | FK → ingested file |
| `status` | Enum | `queued \| in_progress \| done \| unreadable \| failed` |
| `text` | str\|None | None when unreadable or failed |
| `extractor_used` | str\|None | `"markitdown"` or `"paddleocr"` |
| `char_count` | int | 0 when no text |
| `error` | str\|None | None on success |
| `created_at` | datetime | |
| `updated_at` | datetime | |

## Tasks

See `todo_stage2.md` for the full task list and parallel execution map.

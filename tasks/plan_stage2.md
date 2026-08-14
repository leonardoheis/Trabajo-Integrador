# Stage 2: Extraction Hardening

## Responsibility

Stage 1 already extracts text inline (`MarkItDownExtractor` → `OCRExtractor` fallback,
wired into the coordinator's `_extract` step between node2 and node3) — that part is
**done**, not this stage's job. What's missing is everything *around* that call: it runs
unbounded (no concurrency cap), it's invisible to the SSE event stream (unlike node1-4,
which all emit `started`/`passed`/`failed` via `BaseNode`), and its config
(`MIN_TEXT_FOR_OCR`/`MIN_USABLE_TEXT`) is hardcoded rather than driven by
`config/*.yaml` like every other node's thresholds.

This stage closes those three gaps as an incremental hardening pass on the existing
inline extraction step — **not** a rebuild into a separate async pipeline with its own
queue and DB table. That heavier design (originally sketched for this stage) is
deliberately out of scope: nothing about current load demands a dedicated worker pool,
and reusing the existing `DocumentStep` table for observability is a much smaller
surface than a new `ExtractionRecord` model + repository + migration.

## Components

### 1. `ExtractionConfig`

`MIN_TEXT_FOR_OCR = 50` / `MIN_USABLE_TEXT = 20` currently live as hardcoded module
constants in `ingesta/extract.py`. Move them into `config/extraction.yaml` + a Pydantic
config model, matching the `ContentValidationConfig`/`AllowedFormatsConfig` pattern
(`get_extraction_config()`, `@lru_cache`). Add `max_concurrent_extractions` here too —
it's the value the concurrency cap (below) reads.

### 2. Bounded concurrency

A module-level `asyncio.Semaphore(config.max_concurrent_extractions)` wrapping the
extraction call inside the coordinator's `_extract` step. OCR is CPU/GPU-expensive
(confirmed empirically this session — a handful of scanned PDFs took minutes); nothing
today caps how many can run at once across concurrent `/pipeline/ingest` requests. This
is a targeted fix, not a new architecture: no queue, no worker pool, just a shared
semaphore the extraction call acquires before running.

### 3. Extraction observability

Make extraction audit/broadcast-aware like node1-4: emit `extraction: started/passed/
failed` events via `EventBroadcaster`, and record what happened via `AuditService`. Add
`"extraction"` as a new tracked step name in `PipelineService._persist_steps` (reusing
the existing `DocumentStep` table — no new model). Capture `extractor_used`
(`"markitdown"` | `"ocr"`) and status; today neither is recorded anywhere, so a job
that returns empty text is indistinguishable from "MarkItDown got nothing" vs. "OCR
failed" vs. "extraction crashed" without re-running it by hand.

This requires `TextExtractFn`'s return type to grow from a bare `str` to a small result
carrying `text` + `extractor_used` (e.g. an `ExtractionResult` `BaseEntity`, following
the existing `FileReceptionResult`/`FormatValidationResult` shape) — `extract.py`'s
`TextExtractor.__call__` and the coordinator's `_extract` closure both need to thread
that through instead of discarding it.

### 4. Integration test

Prove all three land together: the concurrency cap holds under simulated concurrent
load (an instrumented/mock extractor recording max simultaneous in-flight calls, same
pattern already used for T22's bulk-ingest concurrency test), `extraction` events show
up in the SSE stream in the right order relative to node2/node3, and `extractor_used`
lands in `DocumentStep.detail`.

## Config (`config/extraction.yaml`)

```yaml
min_text_for_ocr: 50            # chars; below this MarkItDown triggers OCR fallback
min_usable_text: 20             # chars; below this text is unusable even after OCR
max_concurrent_extractions: 2   # ponytail: move to config page when UI admin exists
```

## Tasks

See `todo_stage2.md` for the full task list and parallel execution map.

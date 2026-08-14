# Classiflow — Stage 2 Task List

> Prerequisite: Stage 1 complete (merged to `main` via PR #17) — `MarkItDownExtractor`/
> `OCRExtractor` and the coordinator's `_extract` step already exist and are reused
> as-is by this stage, not rebuilt.
> Full details in [plan_stage2.md](plan_stage2.md).
> Status: `[ ]` pending · `[~]` in progress · `[x]` done · `[-]` skipped · `[!]` blocked

---

## Parallel Execution Map

```
BATCH 0  ──────────────────────────────────────────── parallel (no dependencies)
  S2-T01  ExtractionConfig — config/extraction.yaml + Pydantic model
  S2-T02  ExtractionResult domain entity (text + extractor_used)

BATCH 1  ──────────────────────────────────────────── parallel
  S2-T03  Bounded concurrency — asyncio.Semaphore around _extract  (needs S2-T01)
  S2-T04  Extraction observability — SSE events + DocumentStep     (needs S2-T02)
           tracking for the "extraction" step

BATCH 2  ──────────────────────────────────────────── sequential
  S2-T05  Integration test: concurrency cap + event order +        (needs S2-T03 + S2-T04)
           extractor_used persisted
```

---

## Task Details

- [ ] **S2-T01** — `ExtractionConfig`: move `MIN_TEXT_FOR_OCR`/`MIN_USABLE_TEXT` out of
      `extract.py` hardcoded constants into `config/extraction.yaml` + a Pydantic model
      (`get_extraction_config()`, `@lru_cache`, matching `ContentValidationConfig`).
      Add `max_concurrent_extractions`.
      Branch: `feat/extraction-config`

- [ ] **S2-T02** — `ExtractionResult` domain entity (`text: str`, `extractor_used: str`)
      replacing `TextExtractFn`'s bare `str` return. Thread it through
      `extract.py::TextExtractor.__call__` and the coordinator's `_extract` closure.
      Branch: `feat/extraction-result`

- [ ] **S2-T03** — Bounded concurrency: module-level `asyncio.Semaphore` sized from
      `ExtractionConfig.max_concurrent_extractions`, acquired around the extraction
      call in the coordinator's `_extract` step.
      Branch: `feat/extraction-concurrency`

- [ ] **S2-T04** — Extraction observability: `extraction: started/passed/failed` SSE
      events via `EventBroadcaster`; `"extraction"` added as a tracked step name in
      `PipelineService._persist_steps`, storing `extractor_used`/status in the existing
      `DocumentStep` table (no new model/migration).
      Branch: `feat/extraction-observability`

- [ ] **S2-T05** — Integration test: instrumented extractor proves the concurrency cap
      holds under simulated concurrent `/pipeline/ingest` calls; SSE stream shows
      `extraction` events in the right position relative to node2/node3;
      `DocumentStep.detail` contains `extractor_used` for a real run.
      Branch: `feat/extraction-integration-test`

# Classiflow — Stage 2 Task List

> One task = one worktree branch = one PR into `feat/extraction-hardening`.
> Prerequisite: Stage 1 complete (merged to `main` via PR [#17](https://github.com/leonardoheis/Trabajo-Integrador/pull/17)) —
> `MarkItDownExtractor`/`OCRExtractor` and the coordinator's `_extract` step already
> exist and are reused as-is by this stage, not rebuilt.
> Full details in [plan_stage2.md](plan_stage2.md).
> Status: `[ ]` pending · `[~]` in progress · `[x]` done · `[-]` skipped for now · `[!]` blocked

---

## Parallel Execution Map

```
BATCH 0  ──────────────────────────────────────────────── parallel (no dependencies)
  S2-T01  ExtractionConfig
  S2-T02  ExtractionResult domain entity

BATCH 1  ──────────────────────────────────────────────── parallel
  S2-T03  Bounded concurrency (asyncio.Semaphore)      (needs S2-T01)
  S2-T04  ExtractionStep + DocumentStep observability  (needs S2-T02)

BATCH 2  ──────────────────────────────────────────────── sequential (needs S2-T03 + S2-T04)
  S2-T05  Integration test — concurrency + observability

BATCH 3  ──────────────────────────────────────────────── parallel (independent of S2-T01..T05)
  S2-T06  Relocate models to project root + document download sources
  S2-T07  Track playground/samples/ in git
```

---

## Task Cards

### S2-T01 · `ExtractionConfig`
**Branch:** `feat/extraction-config` · **Deps:** none · **Status:** `[x]` `uv run poe check` passing, not yet committed

- [ ] `config/extraction.yaml`: `min_text_for_ocr: 50`, `min_usable_text: 20`,
      `max_concurrent_extractions: 2`
- [ ] `ingesta/config_extraction.py`: `ExtractionConfig(BaseModel)` +
      `get_extraction_config()` with `@lru_cache`, same shape as
      `get_content_validation_config()`
- [ ] `extract.py`'s hardcoded `MIN_TEXT_FOR_OCR`/`MIN_USABLE_TEXT` module constants
      removed, replaced with config reads
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_extract.py
```

---

### S2-T02 · `ExtractionResult` domain entity
**Branch:** `feat/extraction-result` · **Deps:** none · **Status:** `[x]` `uv run poe check` passing, not yet committed

- [ ] `ExtractionResult(BaseEntity)` added to `domain/results.py` alongside
      `FileReceptionResult`/`FormatValidationResult`/`ContentValidationResult`/
      `DuplicateControlResult`: `text: str`, `extractor_used: str`, `char_count: int`
- [ ] `TextExtractor.__call__` returns `ExtractionResult` instead of a bare `str`
- [ ] `extractor_used` correctly reflects which extractor actually produced the
      returned text (`"markitdown"` or `"ocr"`)
- [ ] `coordinator.py`'s `_extract` and any direct test usage updated for the new
      return type
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_extract.py tests/ingesta/test_ocr_extractor.py
```

---

### S2-T03 · Bounded concurrency
**Branch:** `feat/extraction-concurrency` · **Deps:** S2-T01 · **Status:** `[x]` `uv run poe check` passing, not yet committed

- [x] `coordinator.py`'s `_extract` converted from a plain sync closure to
      `async def`, with the blocking `TextExtractor.__call__` wrapped in
      `asyncio.to_thread(...)` — matches node2/node3's own SLM-call pattern rather
      than relying on LangGraph's sync-function thread auto-dispatch
- [x] `asyncio.Semaphore(config.max_concurrent_extractions)` acquired around the
      extraction call — **Container-injected** (`Container.extraction_semaphore` in
      `injections/production.py`, a required `semaphore` constructor param on
      `ExtractionStep`), not a module-level `@lru_cache` getter. A code-smell review
      caught the original module-level-singleton design as a Hidden Dependency
      before it was ever committed; fixed to match `broadcaster`'s existing DI
      pattern instead. See `refactor/di-hidden-singletons` for the same fix applied
      to three other pre-existing singletons elsewhere in `ingesta/`.
- [x] A burst of concurrent `/pipeline/ingest` calls never runs more than
      `max_concurrent_extractions` extractions simultaneously — excess calls wait,
      they don't fail or get dropped
- [x] Existing single-request latency/behavior unchanged
- [x] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_coordinator.py
```

---

### S2-T04 · `ExtractionStep` + `DocumentStep` observability
**Branch:** `feat/extraction-observability` · **Deps:** S2-T02 · **Status:** `[x]` `uv run poe check` passing, not yet committed

- [x] `ingesta/nodes/extraction_step.py`: `ExtractionStep(BaseNode)`,
      `name = "extraction"`, reusing `_emit_started`/`_emit_and_audit` exactly like
      node1-4 — no parallel event-emission path
- [x] `ExtractionStep.run()` always reports `passed=True` — extraction doesn't reject;
      the "no usable text → review" judgment stays in node3 exactly as today
- [x] `coordinator.py`'s `_extract` delegates to `ExtractionStep.run()` instead of
      calling `TextExtractor` directly
- [x] `api/dependencies.py::get_coordinator` builds `ExtractionStep` alongside node1-4
- [x] `services/pipeline/service.py`: `"extraction"` added to `_NODE_NAMES` and the
      `_StepResult` union — persists into the existing `DocumentStep` table, no new
      model/migration
- [x] SSE stream shows `extraction: started` then `extraction: passed` between the
      `node2_format_validation` and `node3_content_validation` events
- [x] `DocumentStep.detail` for the `"extraction"` step contains `text`,
      `extractor_used`, and `char_count` — for every job, not only non-accepted ones
      (closes the gap where `Job.extracted_text` only covers non-accepted jobs, leaving
      accepted documents' text nowhere durable for Stage 3 to read)
- [x] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/api/routes/test_pipeline.py
```

---

### S2-T05 · Integration test — concurrency + observability
**Branch:** `feat/extraction-integration-test` · **Deps:** S2-T03 · S2-T04 · **Status:** `[x]` `uv run poe check` passing, not yet committed

- [ ] Instrumented/mock extractor records max simultaneous in-flight calls under
      simulated concurrent `/pipeline/ingest` load; test proves the cap holds (same
      pattern already used for T22's bulk-ingest concurrency test)
- [ ] Test asserts `extraction` SSE events appear in the right position relative to
      node2/node3
- [ ] Test asserts `extractor_used` is queryable from `DocumentStep` after a real run
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_extraction_concurrency.py
```

---

### S2-T06 · Relocate models to project root + document download sources
**Branch:** `feat/relocate-models` · **Deps:** none · **Status:** `[~]` implemented, not yet verified/committed

- [ ] `src/classiflow/ingesta/models/` moved to `models/` at the repo root (sibling to
      `src/`, `config/`, `data/`)
- [ ] `settings.py`'s `_DEFAULT_MODEL` path updated to
      `_PROJECT_ROOT / "models" / "Phi-4-mini-instruct-Q4_K_M.gguf"` (drops the
      `src/classiflow/ingesta/` path segment)
- [ ] `node4_duplicate_control.py`'s `_get_sentence_model()` passes `cache_folder=`
      pointing into `models/` (new `Settings.EMBEDDING_MODEL_PATH`-style setting,
      matching the `NODE2_MODEL_PATH`/`NODE3_MODEL_PATH` pattern) instead of
      `sentence-transformers`' own default cache directory — both models this project
      actually uses (the SLM GGUF and the `all-MiniLM-L6-v2` embedding model) end up in
      the same place
- [ ] `.gitignore`: remove the `!models/`/`!models/**` un-ignore exception; add a
      `models/**` + `!models/**/.gitkeep` ignore block instead (same shape as the
      existing `data/**` pattern), so everything under the new root `models/` is
      ignored regardless of file extension — `*.gguf` is already covered by an
      existing rule, but the embedding model's `.safetensors`/`config.json`/tokenizer
      files aren't caught by any current extension-based rule
- [ ] `README.md`: new "Models" section documenting both models — name, purpose (SLM:
      node2/node3 decisions; embedding model: node4 duplicate detection), the exact
      Hugging Face source, and the download command/target path for each
- [ ] **Open item to resolve during this task, not before starting it**: confirm the
      exact Hugging Face repo `Phi-4-mini-instruct-Q4_K_M.gguf` was actually sourced
      from — multiple community GGUF conversions of this model share the same
      filename, so this needs verifying against the file's content hash, not assuming
      one. The commit/etag hashes from `.cache/huggingface/download/*.metadata` are
      already on hand from this session's earlier investigation.
- [ ] Fresh clone + `uv sync --dev` + downloading both models per the new README
      instructions reaches a working `uv run poe check` — proves the relocation didn't
      silently break model loading
- [ ] `uv run poe check` passes

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_llm_provider.py tests/ingesta/test_node4.py
```

---

### S2-T07 · Track `playground/samples/` in git
**Branch:** `feat/track-playground-samples` · **Deps:** none · **Status:** `[~]` implemented, not yet verified/committed

- [ ] `.gitignore`'s blanket `samples/` rule removed (or narrowed to exactly
      `src/classiflow/playground/samples/` if a broader `samples/` ignore turns out to
      be needed for something else — check before removing outright)
- [ ] Sample PDFs currently in `src/classiflow/playground/samples/` committed to git,
      so `pipeline_end_to_end.ipynb`/`text_extraction.ipynb`/`pipeline_benchmark.ipynb`
      work for a fresh clone without manually re-sourcing files
- [ ] Total added size checked before committing — municipal PDFs, a few hundred KB to
      ~1MB each based on this session's runs, not something that should silently
      balloon repo size
- [ ] `uv run poe check` passes (nothing currently tests this directly, but confirms
      nothing else broke)

```bash
# Verify
git status src/classiflow/playground/samples/
du -sh src/classiflow/playground/samples/
```

---

## Progress

| Task | Description | Status |
|---|---|---|
| S2-T01 | `ExtractionConfig` | `[x]` `poe check` passing, not committed |
| S2-T02 | `ExtractionResult` domain entity | `[x]` `poe check` passing, not committed |
| S2-T03 | Bounded concurrency (`asyncio.Semaphore`) | `[x]` `poe check` passing, not committed |
| S2-T04 | `ExtractionStep` + `DocumentStep` observability | `[x]` `poe check` passing, not committed |
| S2-T05 | Integration test — concurrency + observability | `[x]` `poe check` passing, not committed |
| S2-T06 | Relocate models to project root + document download sources | `[~]` implemented, not yet verified |
| S2-T07 | Track `playground/samples/` in git | `[~]` implemented, not yet verified |

**7 / 7 tasks implemented** — none committed yet, and S2-T06/S2-T07 haven't had
`uv run poe check` run against them yet (S2-T01..T05 passed as of the last check run).

**Next up**: run `uv run poe check` on the full current diff, then commit/PR
`feat/extraction-hardening` — every planned Stage 2 task is now implemented.

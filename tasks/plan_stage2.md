# Implementation Plan: Classiflow — Stage 2: Extraction Hardening

**Status: implemented.** All 7 tasks (S2-T01–T07) below are done and committed to
`feat/extraction-hardening` (plus follow-up hidden-dependency DI fixes and typing
cleanup merged via PR [#18](https://github.com/leonardoheis/Trabajo-Integrador/pull/18)
and [#19](https://github.com/leonardoheis/Trabajo-Integrador/pull/19) — see "Additional
work beyond this plan" at the end). The branch itself is not yet merged to `main`.

## Project Context

Stage 1 (`feat/ingesta-pipeline` → `main`, PR [#17](https://github.com/leonardoheis/Trabajo-Integrador/pull/17)) shipped the full 4-node ingestion pipeline **and** text
extraction — `MarkItDownExtractor` → `OCRExtractor` (EasyOCR) fallback, wired inline
into the LangGraph coordinator's `_extract` step between node2 and node3. That work is
done and is **not** in scope here.

What Stage 1 didn't build: any operational scaffolding around that extraction call. It
runs with no concurrency cap, it's invisible to the SSE event stream (unlike node1-4,
which all emit `started`/`passed`/`failed` via `BaseNode`), and its thresholds
(`MIN_TEXT_FOR_OCR`/`MIN_USABLE_TEXT`) are hardcoded module constants instead of
YAML-driven config like every other node. Stage 2 closes those three gaps.

## Responsibility

Make the existing extraction step observable and bounded. Explicitly **not**
responsibility of this stage: re-implementing extraction, changing the MarkItDown→OCR
fallback logic, or moving extraction out of the per-job coordinator run into a separate
async pipeline. Text extraction is a solved problem as of Stage 1; this stage only adds
visibility and a concurrency ceiling around it.

## Architecture Decisions

**Hardening, not a rebuild.** The original Stage 2 sketch (superseded — see git history
of this file) proposed a fully decoupled async pipeline: its own `asyncio.Queue`,
dedicated worker pool, and a new `ExtractionRecord` DB table + repository + migration.
That's the right design *if* extraction ever needs to scale across processes — nothing
about current load demands it yet, and it would duplicate machinery
(`DocumentStep`/`EventBroadcaster`) that already does the same job for node1-4. Reusing
that existing machinery for extraction is a smaller, faster, equally-correct path to
the same visibility.

**`asyncio.Semaphore`, not `threading.Semaphore` — and why `_extract` has to become
`async def` first.** `_extract` today is a plain *sync* closure in `coordinator.py`;
LangGraph auto-dispatches plain sync node functions to its own thread pool (this is
intentional — see `BaseNode`'s doc comment on why node2/node3 use `asyncio.to_thread`
instead of relying on that auto-dispatch: it only applies to sync functions, not
coroutines). A sync function can't `await` an `asyncio.Semaphore`. So bounding
concurrency correctly requires converting `_extract` to `async def` first (matching
node1-4's own pattern) and moving the blocking extraction call behind
`asyncio.to_thread`, *then* wrapping that in `async with semaphore:`. Doing this also
unifies `_extract` with the rest of the coordinator instead of leaving it as the one
node with a different execution model.

**Reuse `DocumentStep`, don't add `ExtractionRecord`.** `DocumentStep` already stores
one row per node per job with `status`/`passed`/`detail` (JSON). Adding `"extraction"`
as a tracked step name gets the same queryability (`extractor_used`, `char_count`,
status) the original `ExtractionRecord` model would have provided, with zero schema
migration and zero new repository.

**Extraction never rejects.** The new `ExtractionStep` node always reports
`passed=True` for audit/`DocumentStep` purposes — the "no usable text → route to human
review" judgment call stays exactly where it is today, inside node3's `validate()`.
Moving that judgment into extraction would be a real behavior change, not hardening.

## File Layout (target state)

```
config/
└── extraction.yaml                     new — min_text_for_ocr, min_usable_text,
                                         max_concurrent_extractions

src/classiflow/ingesta/
├── config_extraction.py                new — ExtractionConfig, get_extraction_config()
├── extract.py                          modified — TextExtractor.__call__ returns
│                                        ExtractionResult (was: bare str); gains
│                                        asyncio.Semaphore acquire around the call
├── domain/
│   └── results.py                      modified — + ExtractionResult(BaseEntity)
├── nodes/
│   └── extraction_step.py              new — ExtractionStep(BaseNode), name="extraction"
└── coordinator.py                      modified — _extract becomes async def,
                                         delegates to ExtractionStep.run()

src/classiflow/
├── api/dependencies.py                 modified — get_coordinator() builds
│                                        ExtractionStep alongside node1-4
└── services/pipeline/service.py        modified — _NODE_NAMES + _StepResult gain
                                         "extraction"

tests/ingesta/
├── test_extraction_step.py             new — mirrors test_node1.py's shape
└── test_extraction_concurrency.py      new — instrumented extractor proves the
                                         semaphore cap holds under concurrent load
```

## Dependency Graph

```
config/extraction.yaml ─────────────────────► ExtractionConfig
ExtractionConfig ───────────────────────────► extract.py (semaphore size, thresholds)

domain/results.py (ExtractionResult) ───────► extract.py (TextExtractor return type)
                                     └───────► nodes/extraction_step.py

nodes/extraction_step.py ───────────────────► coordinator.py (_extract)
extract.py (semaphore) ─────────────────────► coordinator.py (_extract, via async to_thread)

coordinator.py ──────────────────────────────► api/dependencies.py (get_coordinator)
services/pipeline/service.py ───────────────► DocumentStep persistence ("extraction" step)
```

---

## Phase 1: Config

### Task S2-T01: `ExtractionConfig`

**Description:** Move `MIN_TEXT_FOR_OCR`/`MIN_USABLE_TEXT` out of `extract.py`'s
hardcoded module constants into `config/extraction.yaml` + a Pydantic model, matching
`ContentValidationConfig`/`config_content.py`. Add `max_concurrent_extractions` here —
it's what Phase 3's semaphore reads.

**Acceptance criteria:**
- [x] `config/extraction.yaml`: `min_text_for_ocr: 50`, `min_usable_text: 20`,
      `max_concurrent_extractions: 2`
- [x] `ingesta/config_extraction.py`: `ExtractionConfig(BaseModel)` +
      `get_extraction_config()` with `@lru_cache`, same shape as `get_content_validation_config()`
- [x] `extract.py`'s module constants removed, replaced with config reads
- [x] `uv run poe check` passes

**Dependencies:** None

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_extract.py
```

---

## Phase 2: Domain entity

### Task S2-T02: `ExtractionResult`

**Description:** Add `ExtractionResult(BaseEntity)` to `domain/results.py` alongside
`FileReceptionResult`/`FormatValidationResult`/etc: `text: str`, `extractor_used: str`,
`char_count: int`. `extract.py`'s `TextExtractor.__call__` return type changes from a
bare `str` to `ExtractionResult`.

**Acceptance criteria:**
- [x] `ExtractionResult(BaseEntity)` added to `domain/results.py`
- [x] `TextExtractor.__call__` returns `ExtractionResult` instead of `str`
- [x] `extractor_used` set to `"markitdown"` or `"ocr"` depending on which extractor
      actually produced usable text
- [x] Existing callers of `TextExtractor`/`TextExtractFn` updated for the new return
      type (`coordinator.py`'s `_extract`, any direct test usage)
- [x] `uv run poe check` passes

**Dependencies:** None (parallel with S2-T01)

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_extract.py tests/ingesta/test_ocr_extractor.py
```

---

## Phase 3: Bounded concurrency

### Task S2-T03: `asyncio.Semaphore` around extraction

**Description:** Convert `coordinator.py`'s `_extract` from a plain sync closure to
`async def`, wrapping the blocking `TextExtractor.__call__` in
`asyncio.to_thread(...)` — matching node2/node3's own SLM-call pattern instead of
relying on LangGraph's sync-function auto-dispatch. A module-level
`asyncio.Semaphore(config.max_concurrent_extractions)` is acquired around that call, so
concurrent `/pipeline/ingest` requests can't run unbounded OCR simultaneously.

**Acceptance criteria:**
- [x] `_extract` is `async def`; blocking extraction work runs via `asyncio.to_thread`
- [x] Semaphore sized from `ExtractionConfig.max_concurrent_extractions`, acquired
      around the extraction call (`async with semaphore:`) — **Container-injected**
      (`Container.extraction_semaphore`), not a module-level singleton; a code-smell
      review caught the original module-level-getter design as a Hidden Dependency
      before it was committed
- [x] A burst of concurrent `/pipeline/ingest` calls never has more than
      `max_concurrent_extractions` extractions actually running at once — the rest
      wait, they don't fail or get dropped
- [x] Existing single-request latency/behavior unchanged
- [x] `uv run poe check` passes

**Dependencies:** S2-T01 (needs `ExtractionConfig`)

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_coordinator.py
```

---

## Phase 4: Observability

### Task S2-T04: `ExtractionStep` + `DocumentStep` tracking

**Description:** New `ingesta/nodes/extraction_step.py`: `ExtractionStep(BaseNode)`,
`name = "extraction"`, reusing `_emit_started`/`_emit_and_audit` exactly like node1-4
— no parallel event-emission path. Always reports `passed=True` (extraction doesn't
reject; see Architecture Decisions above). `coordinator.py`'s `_extract` delegates to
`ExtractionStep.run()` instead of calling `TextExtractor` directly.
`PipelineService._persist_steps` gains `"extraction"` in `_NODE_NAMES` and the
`_StepResult` union, so it lands in `DocumentStep` through the existing persistence
loop — no new table.

**`detail` carries the full extracted text, for every job — not just metadata.**
Closes a real gap surfaced while planning Stage 3: `Job.extracted_text` only persists
text for non-accepted jobs (a deliberate storage-bounding choice made earlier), so
nothing durable held the text of an *accepted* document once its job finished — and
Stage 3 (enrichment) needs exactly that text for every document that reaches it, not
only the rejected/review ones. Storing it in the `"extraction"` `DocumentStep.detail`
(alongside `extractor_used`/`char_count`) closes that gap without a new table or a
second copy of the "only store for non-accepted" logic `Job.extracted_text` already has.

**Acceptance criteria:**
- [x] `ExtractionStep(BaseNode)` in `nodes/extraction_step.py`, `name = "extraction"`
- [x] SSE stream shows `extraction: started` then `extraction: passed` between
      `node2_format_validation` and `node3_content_validation` events
- [x] `DocumentStep` row written for the `"extraction"` step, `detail` containing
      `text` + `extractor_used` + `char_count` — for every job, regardless of the
      pipeline's eventual accept/reject/review outcome
- [x] `api/dependencies.py::get_coordinator` builds `ExtractionStep` alongside node1-4
- [x] `uv run poe check` passes

**Dependencies:** S2-T02 (needs `ExtractionResult`)

```bash
# Verify
uv run poe check
uv run poe test tests/api/routes/test_pipeline.py
```

---

## Phase 5: Integration test

### Task S2-T05: Concurrency + observability integration test

**Description:** Prove S2-T03 and S2-T04 actually hold together, not just in
isolation: an instrumented/mock extractor records max simultaneous in-flight calls
under concurrent load (same pattern already used for T22's bulk-ingest concurrency
test), the SSE stream carries `extraction` events in the right order, and
`DocumentStep.detail` contains `extractor_used` for a real run.

**Acceptance criteria:**
- [x] Test proves the concurrency cap holds under simulated concurrent
      `/pipeline/ingest` calls
- [x] Test asserts `extraction` events appear in the SSE stream between node2 and node3
- [x] Test asserts `extractor_used` is queryable from `DocumentStep` after a run
- [x] `uv run poe check` passes

**Dependencies:** S2-T03 · S2-T04

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_extraction_concurrency.py
```

---

## Phase 6: Reproducible model setup

### Task S2-T06: Relocate models to project root + document download sources

**Description:** Independent of the S2-T01..T05 extraction work — this is about
whether a fresh clone of this repo can actually run it. Today the SLM GGUF lives at
`src/classiflow/ingesta/models/` and is committed to git via a `!models/`/`!models/**`
`.gitignore` exception; the embedding model (`sentence-transformers/all-MiniLM-L6-v2`,
used by node4 for duplicate detection — see `node4_duplicate_control.py:21,39`)
downloads to `sentence-transformers`' own default cache, invisible to this repo
entirely. Neither is documented anywhere. Move both to a `models/` directory at the
repo root, ignore it properly, and document exactly how to repopulate it from a clean
clone.

**Acceptance criteria:**
- [x] `src/classiflow/ingesta/models/` moved to `models/` at the repo root
- [x] `settings.py`'s `_DEFAULT_MODEL` updated to
      `_PROJECT_ROOT / "models" / "Phi-4-mini-instruct-Q4_K_M.gguf"`
- [x] `node4_duplicate_control.py`'s `_get_sentence_model()` passes `cache_folder=`
      pointing into `models/` via a new `Settings.EMBEDDING_MODEL_PATH`-style setting
- [x] `.gitignore`: `!models/`/`!models/**` exception removed; replaced with
      `models/**` + `!models/**/.gitkeep`, matching the existing `data/**` pattern —
      covers the embedding model's config/tokenizer files, which no current
      extension-based rule catches
- [x] `README.md` gains a "Models" section: name, purpose, Hugging Face source, and
      download command/target path for each of the two models
- [x] The exact HF repo `Phi-4-mini-instruct-Q4_K_M.gguf` was sourced from is confirmed —
      [unsloth/Phi-4-mini-instruct-GGUF](https://huggingface.co/unsloth/Phi-4-mini-instruct-GGUF)
- [x] Fresh clone + `uv sync --dev` + following the new README instructions reaches a
      working `uv run poe check`
- [x] `uv run poe check` passes

**Dependencies:** None (touches `settings.py`/`.gitignore`/`README.md`, not the
extraction pipeline itself — safe to do in parallel with S2-T01..T05)

```bash
# Verify
uv run poe check
uv run poe test tests/ingesta/test_llm_provider.py tests/ingesta/test_node4.py
```

---

## Phase 7: Sample fixtures

### Task S2-T07: Track `playground/samples/` in git

**Description:** `.gitignore`'s blanket `samples/` rule has silently excluded
`src/classiflow/playground/samples/` from every commit this whole project — the sample
PDFs this session's notebooks (`pipeline_end_to_end.ipynb`, `text_extraction.ipynb`,
`pipeline_benchmark.ipynb`) depend on only exist locally. A fresh clone can't run any
of them today.

**Acceptance criteria:**
- [x] `.gitignore`'s `samples/` rule removed or narrowed to exactly this directory
- [x] Sample PDFs in `src/classiflow/playground/samples/` committed
- [x] Total added size checked before committing (municipal PDFs, expected a few
      hundred KB to ~1MB each)
- [x] `uv run poe check` passes

**Dependencies:** None

```bash
# Verify
git status src/classiflow/playground/samples/
du -sh src/classiflow/playground/samples/
```

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Converting `_extract` to `async def` changes its execution model (thread-pool auto-dispatch → explicit `to_thread`) | Medium | Behavior should be equivalent; covered by existing `test_coordinator.py` end-to-end tests, re-run before merge |
| Semaphore contention adds latency under genuine load spikes | Low | That's the intended tradeoff (bounded, predictable throughput over unbounded parallelism) — same rationale already accepted for T22's bulk-ingest semaphore |
| `ExtractionResult` return-type change breaks any test constructing `TextExtractor` output directly | Low | `tests/ingesta/test_extract.py` already covers `TextExtractor` directly; update alongside S2-T02 |
| `"extraction"` step ordering in SSE stream surprises a frontend expecting only node1-4 | Low | No frontend consumes this yet (per architecture doc, web UI is unbuilt); document the new event in whichever task builds it |
| Wrong HF repo identified for the SLM GGUF, README sends a fresh clone to a different file than what's actually been tested against | Medium | Confirm by content hash before writing it into the README, not by filename match alone (several repos share the filename) |
| Committing `playground/samples/` grows repo size more than expected | Low | Check `du -sh` before committing (S2-T07); these are individual municipal PDFs, not a bulk dataset dump |

## Tasks

See `todo_stage2.md` for the full task list and parallel execution map.

## Additional work beyond this plan

A `/code-smells` review of the S2-T03 semaphore surfaced a broader Hidden Dependency
pattern already present elsewhere in `ingesta/` (module-level `@lru_cache` singleton
getters instead of Container-managed dependencies). Fixed together, beyond this plan's
original scope, and merged via two follow-up PRs into `feat/extraction-hardening`:

- **PR [#18](https://github.com/leonardoheis/Trabajo-Integrador/pull/18)** —
  `get_language_detector` (node3), `get_sentence_model`/`embedding_store` (node4), and
  the node2/node3 SLM chains wired through the DI `Container`, matching the existing
  `broadcaster`/`text_extractor` pattern. Also fixed a real bug found in the process:
  `embedding_store` was previously rebuilt empty on every request (a `Factory`, not a
  `Singleton`), so semantic near-duplicate detection was silently a no-op in
  production — only exact SHA-256 dedup ever worked.
- **PR [#19](https://github.com/leonardoheis/Trabajo-Integrador/pull/19)** — replaced
  `coordinator.py`'s `dict[str, Any]` node-closure returns with a typed `NodeUpdate`
  pydantic model.

Further cleanup after both PRs merged (still on `feat/extraction-hardening`, uncommitted
as of this plan update — see git status before assuming these are on `main`):

- Completed the `nodes`/`domain`/`prompts` package `__init__.py` re-exports (they
  existed but were stale/unused — every consumer imported from the submodule directly)
  and migrated every consumer to the package-level import.
- Deleted dead config fields (`DuplicateControlConfig.on_duplicate`,
  `ContentValidationConfig.max_chars` — declared, loaded from YAML, never read) and the
  unused, `Any`-typed `NodeEvent.detail` field.
- Added a shared `config_loader.py` to de-duplicate the four near-identical
  `@lru_cache` + YAML-loading config modules.
- `ingesta/exceptions.py`'s `ModelNotFoundError`/`ModelLoadError` converted to this
  project's `@dataclass` exception convention (was hand-rolled `__init__`).
- `FormatChainInput`/`ContentChainInput`/`FormatDecisionOutput`/`LegitimacyDecisionOutput`
  (the two SLM prompt chains' input/output types) converted from `dict[str, str]` to
  `BaseEntity` models — removed a `PromptTemplate` dependency entirely in the process,
  which also eliminated two `cast()`s that existed only to bridge LangChain's own
  `dict[str, Any]`-typed internals.
- `DEPLOY.md` deleted (superseded — its scale-estimate table merged into `README.md`'s
  "Document Categories" table).
- `playground/stage1/pipeline_benchmark.ipynb` fixed (its `ExtractionStep(...)` call was
  missing the now-required `semaphore=` argument — broken since S2-T03 landed, unnoticed
  because `poe check`'s `nbtest` step doesn't cover `playground/`). New
  `playground/stage2/extraction_concurrency.ipynb` added, demonstrating the S2-T03
  concurrency cap and S2-T04 observability interactively.

# Design: Stage 4 — Classification & Routing

## Context

`tasks/plan_stage4.md` and `tasks/todo_stage4.md` already sketch Stage 4's shape: take
an `EnrichedRecord` (Stage 3 output, merged to `main`) and produce a classification
decision plus a routing outcome. A prior spec,
`docs/superpowers/specs/2026-08-17-bert-tunning-classification-integration-design.md`
("the BERT spec"), already fully designed **one piece** of this — the Second Opinion
Agent's real BETO/BERT backing, the `classification/` package boundary, and the
`BaseNode`/`config_loader.py` relocation (executed as part of Stage 3). That spec
explicitly left the Primary Classification Agent, Confidence Gate, LLM Judge, and
Routing Agent undesigned.

This spec resolves everything the BERT spec left open, and adds one thing neither prior
document anticipated: a real files-on-disk directory structure for classified/
under-review documents, driven by an explicit product decision made during this
brainstorm (not just DB rows, as Stage 1-3's `/review-queue` already is). That decision
has a real implication — Stage 1 currently never persists uploaded file bytes anywhere
durable — which pulls one Stage-1-owned backlog item (T22, bulk ingest) into this
spec's scope and requires one small, targeted change to `PipelineService._run()`.

The BERT spec's decisions (package layout, label-space mapping, `ClassificationRecord`'s
BERT-related fields) are treated as settled and are not re-litigated here; this spec's
`ClassificationRecord` section only adds the fields the BERT spec didn't cover.

## Decisions

### 1. Storage: local disk now, behind a swappable seam — new `classiflow/storage/` package

Real files land on disk, organized by outcome, with a path to move to a blob backend
(Azure Blob, S3, ...) later without touching any calling code. Follows this codebase's
own established Protocol + concrete-implementation pattern (`IJobRepository` /
`SqlJobRepository`) rather than reaching for a cloud SDK now — no deployment target
needs one yet, and Azure Blob (account, SDK, credentials, cost) or a local emulator
(Azurite/MinIO) buys nothing today.

```python
class IDocumentStorage(Protocol):
    async def save_staged(self, job_id: str, filename: str, file_bytes: bytes) -> str: ...
    async def move_to_final(self, job_id: str, filename: str, subdirectory: str) -> str: ...
```

`save_staged` writes to `<root>/staging/<job_id>_<filename>`, returns that path.
`move_to_final` moves the staged file to `<root>/<subdirectory>/<job_id>_<filename>`
(creating parent directories as needed) and returns the new path — `subdirectory` is
either `classified/<label>` or `review/human_review` (see Decision 8). The `<job_id>_`
prefix avoids collisions between different jobs that share a filename.

`LocalDiskStorage` is the only implementation built now, rooted at
`Settings.DOCUMENT_STORAGE_ROOT` (new setting, same `UPPER_CASE` field +
`lower_case` property pattern as `NODE2_MODEL_PATH`/`node2_model_path`, default
`str(_PROJECT_ROOT / "storage" / "documents")`). It lives in `classiflow/storage/`, a
new top-level package (not inside `classification/`) — Stage 1 needs `save_staged`
too, and `ingesta` depending on `classification` would be the wrong direction, the same
kind of cross-package concern already noted and accepted for
`enrichment/` → `ingesta.llm_provider` in the Stage 3 spec, avoidable here since the
package doesn't exist yet.

Not built now: idempotency handling for `move_to_final` being called twice on the same
job. Routing only ever runs once per job's terminal state (Decision 8's two call sites
are mutually exclusive per job), so a second call is a genuine bug, not an expected
case — let `shutil.move`'s `FileNotFoundError` surface it rather than adding a
defensive check for something that shouldn't happen.

### 2. Stage 1 change: persist raw bytes to staging inside `PipelineService._run()`

`_run(self, job_id, filename, file_bytes)` already holds `file_bytes` in scope for the
method's entire body (`services/pipeline/service.py:78-92`) — it's never currently
persisted anywhere durable. Add one call, right after `_persist_steps` and before
`_finalize_job`, gated on extraction having actually produced something (not on
`final_status`, since staging needs to happen even for jobs that later land in
`human_review`, and orphaning a staged file for a job rejected *after* extraction by
node3/node4 is an accepted, harmless cost — see Open Items):

```python
if final_state.get("extraction") is not None:
    await self._document_storage.save_staged(job_id, filename, file_bytes)
```

This is the *only* place bytes get persisted — it fires for both `POST /pipeline/ingest`
and `POST /pipeline/ingest-bulk` (T22, see Decision 3) for free, since both dispatch
through this same method. No new coordinator node, no change to the LangGraph graph
itself.

### 3. T22 (bulk ingest) moves into Stage 4's scope, unchanged in design

`tasks/todo.md`'s T22 (`feat/bulk-ingest`, currently `[ ]` pending under Stage 1) is
re-scoped as a Stage 4 task. Its own design (`POST /pipeline/ingest-bulk`, bounded
`asyncio.Semaphore`, one `Job` row per file, same SSE contract) is unchanged — it needs
no bespoke persistence logic of its own, because Decision 2 puts staging in the shared
`_run()` path both the single-file and bulk endpoints already call through. Its
acceptance criteria gain one line: "each bulk-submitted file lands in staging the same
as single-file ingest."

### 4. Primary Classification Agent: same LLM chain pattern as node2/node3/entity-extraction

A `BaseEntity` chain-input model, a `.format()`-based prompt template, a
`RunnableLambda | llm | StrOutputParser() | RunnableLambda` chain, `get_llm_langchain()`
called with a new `Settings.classification_model_path` (own `@lru_cache` slot, same
model-swap mechanism already used for node2/node3/enrichment — a Gemma 4 GGUF works
here with zero code change, see Decision 7).

```python
class PrimaryClassificationInput(BaseEntity):
    cleaned_text: str  # truncated to config.max_input_tokens before this model is built


class PrimaryClassificationOutput(BaseEntity):
    label: str
    confidence: float
    all_scores: dict[str, float] = {}
```

Truncation happens in the node, not the prompt template, so the truncation length stays
a single config-driven decision (`ClassificationConfig.max_input_tokens`, already in
`plan_stage4.md`) rather than baked into a template string.

### 5. Second Opinion Agent, Foreign Municipality, Smells/Risk, Confidence Gate — unchanged

Fully designed already:
- **Second Opinion Agent** — the BERT spec, in full (label mapping, OOD/SVM scoring,
  `classifier_disagreement` semantics). Not re-litigated here.
- **Foreign municipality detection** — `plan_stage4.md`'s description (ported from
  `bert_tunning`'s `detect_foreign_municipality`). Not re-litigated here.
- **Smells + Risk Score** — `plan_stage4.md`'s weights table
  (`unreadable_document`:3, `classifier_disagreement`:3, `foreign_municipality`:2,
  `low_svm_margin`:2, `low_confidence`:1) and `risk_score = sum(weights of fired
  smells)`, `smell_review_suggested = risk_score > smell_review_risk_threshold`.
  Unchanged.
- **Confidence Gate** — `plan_stage4.md`'s `decide_review_route` logic, unchanged:

```
if foreign_municipality or classifier_disagreement:
    review_route = "human_review"
elif confidence >= confidence_threshold:
    review_route = "accept"
else:
    review_route = "llm_judge"
```

One clarification this spec adds: **`"llm_judge"` is never a persisted or routed
terminal state.** It always resolves to `"accept"` or `"human_review"` before Routing
runs (Decision 8) — there is no third staging folder for "awaiting judge," confirmed
during this brainstorm. `ClassificationRecord.review_route` only ever holds `"accept"`
or `"human_review"` once a row reaches Routing.

### 6. LLM Judge tier: single structured LLM call, no tool use — for now

For `llm_judge`-routed predictions, run a second, focused LLM pass over the **full**
(untruncated) `cleaned_text` and re-decide `accept` vs. `human_review`. Same
`BaseEntity` chain pattern as Decision 4, own `Settings.judge_model_path` (can be a
different, more careful model than the primary classifier — e.g. a larger Gemma 4
variant — independently overridable, same per-agent-model-path convention as
node2/node3/enrichment).

**No tool-use/agentic pattern for the Judge**, despite it being raised during this
brainstorm — deliberately rejected for now. Everything the Judge would reason over
(`cleaned_text`, primary classifier's `all_scores`, second opinion's label/OOD metrics,
`smells`, `risk_score`, `foreign_municipality`) is already computed by upstream nodes in
the *same* pipeline run and available as prompt content — there's nothing dynamic left
to fetch, so a tool has nothing to do. A tool earns its keep once Stage 5's knowledge
base exists and the Judge can retrieve genuinely unknown context (similar
previously-classified documents, official taxonomy definitions) — noted here as a
justified future upgrade, not built speculatively now.

### 7. Model swap: Gemma 4 (E2B/E4B) confirmed usable via `llama_cpp`, zero code change

`get_llm_langchain()` (`ingesta/llm_provider.py`) is architecture-agnostic — it loads
whatever GGUF `Settings.xxx_MODEL_PATH` points at. Gemma 4 (launched April 2026) has
day-one `llama.cpp` support with public E2B/E4B/26B-A4B/31B GGUF releases. Swapping any
Stage 4 agent (primary classifier, Judge) to Gemma 4 is a config change only — point
`Settings.CLASSIFICATION_MODEL_PATH` / `Settings.JUDGE_MODEL_PATH` at a Gemma 4 GGUF.
Verify the installed `llama-cpp-python` version against the target GGUF's quantization
before pulling a large file down; not otherwise gated by this spec.

### 8. Routing Agent: deterministic `BaseNode`, not an LLM/tool-using agent

Explicitly considered and rejected during this brainstorm. By the time Routing runs,
`label` and `review_route` are already fully computed — there is no ambiguity for an
LLM to resolve, only a pure function of two known values. This also matches how every
other "agent" in this codebase is actually built: node1/node4 are plain deterministic
`BaseNode`s, node2/node3 use an LLM only for the part that's a genuine judgment call.
Routing isn't that part.

```python
class RoutingNode(BaseNode):
    def __init__(
        self, audit, broadcaster, storage: IDocumentStorage,
        classification_repo: IClassificationRecordRepository,
    ) -> None: ...

    async def run(
        self, ctx: JobContext, filename: str, label: str, review_route: ReviewRoute
    ) -> RoutingResult:
        subdirectory = f"classified/{label}" if review_route == "accept" else "review/human_review"
        stored_path = await self.storage.move_to_final(ctx.job_id, filename, subdirectory)
        # audit entry: label, confidence, review_route, smells, risk_score,
        # smell_review_suggested, stored_path, timestamp (plan_stage4.md's
        # "audit log entry for every document" requirement)
        return RoutingResult(stored_path=stored_path)
```

Two terminal destinations only, matching Decision 5's clarification: `classified/<label>/`
(accept) and `review/human_review/` (human_review). Called from **two** places (Decision
9): automatically at the end of the Stage 4 coordinator run, and directly (not through
LangGraph) from the new human-decision endpoint.

### 9. Human review → later routing: reuses existing infra, no pipeline "resume"

Stage 1-3's existing `/pipeline/{job_id}/decision` (`accept|reject|escalate`, guarded on
`Job.status == "review"`) doesn't fit — Stage 4's human-review case is a document that
already passed Stage 1-3; the human needs to supply a *label*, not accept/reject the
document itself. New, separate decision surface:

- `GET /classification/review-queue` — lists `ClassificationRecord` rows with
  `review_route == "human_review"`, mirroring the existing `/review-queue` shape but
  scoped to the `classification/` package.
- `POST /classification/{job_id}/decision` — body `{label: str, notes: str | None}`.
  Guarded on `ClassificationRecord.review_route == "human_review"` (new
  `ClassificationNotInReviewError` in `classification/exceptions.py`, same
  dataclass-subclass style as the rest of the codebase). On success: updates the record
  (`label = body.label`, `review_route = "accept"`, `human_overridden = True`), records
  an audit entry via the existing `AuditService` (no new decision table — the generic
  `AuditRecord` model already carries `job_id`/`node`/`event`/`detail` JSON, reused here
  rather than duplicating `HumanDecision`'s shape for a different concern), then calls
  `RoutingNode.run(...)` **directly** with the human-supplied label.

No pipeline-resume machinery needed: Routing has no upstream state dependency beyond
`(job_id, filename, label, review_route)`, so it's just a small unit callable from two
places — automatic and human-triggered — the same way today's `/decision` endpoint
already calls `job_repo.update_status()` directly rather than resuming anything.

`Job.status` is untouched by this endpoint — it's already `"accepted"` from Stage 1-3
by the time a `ClassificationRecord` exists at all. Only `ClassificationRecord` changes;
`Job.status` and `ClassificationRecord.review_route` are deliberately separate concerns
(ingestion-pipeline outcome vs. classification outcome), same reasoning already applied
when scoping the new decision endpoint instead of reusing `/pipeline/{job_id}/decision`.

### 10. Trigger: automatic, chained inside `PipelineService._run()`, same shape as Stage 3

Stage 4 runs immediately after Stage 3 succeeds, mirroring
`if final_state.get("final_status") == "accepted": await self._run_enrichment(...)`.
`_run_enrichment` changes to return the saved `EnrichedRecord` (or `None` on failure,
after retries are exhausted) so `_run()` can chain:

```python
enriched_record = await self._run_enrichment(job_id, filename, final_state)
if enriched_record is not None:
    await self._run_classification(job_id, filename, enriched_record)
```

`_run_classification` builds the classification coordinator's initial state from
`enriched_record.cleaned_text`, runs primary classification → second opinion → foreign
municipality → smells/risk → confidence gate → (conditionally) LLM judge → Routing, all
within the same background task as Stage 1-3, and persists the resulting
`ClassificationRecord`.

## `ClassificationRecord` — fields this spec adds beyond the BERT spec

The BERT spec already defined `id`, `job_id`, `enriched_id`, `label`, `confidence`,
`all_scores`, `second_opinion_label`, `second_opinion_confidence`,
`classifier_disagreement`, `ood_metrics`, `svm_scores`, `svm_agrees_with_prediction`,
`review_route`, `smells`, `risk_score`, `smell_review_suggested`, `foreign_municipality`,
`created_at` — all `Integer`/`autoincrement=True` id (this project's convention, not
UUID, already corrected once for `EnrichedRecord`). This spec adds:

| Field | Type | Purpose |
|---|---|---|
| `judged_by_llm` | `bool` | Whether the LLM Judge tier ran and produced the final `review_route` (Decision 6) |
| `stored_path` | `str \| None` | Set by `RoutingNode` once the file has been moved to its final location (Decision 8) |
| `human_overridden` | `bool` (default `False`) | Set by the human-decision endpoint (Decision 9) |

## File layout

```
src/classiflow/storage/
├── document_storage.py              IDocumentStorage Protocol, LocalDiskStorage

src/classiflow/classification/       (package boundary + BERT internals per the BERT spec)
├── config_classification.py         ClassificationConfig + get_classification_config()
├── exceptions.py                    ClassificationRecordNotFoundError, ClassificationNotInReviewError
├── domain/
│   └── results.py                   PrimaryClassificationOutput, JudgeOutput, RoutingResult (BaseEntity)
├── bert/                            ported bert_tunning code — per the BERT spec, unchanged
├── prompts/
│   ├── primary_classification.py    PrimaryClassificationInput/Output + build_classification_chain()
│   └── llm_judge.py                 JudgeInput/Output + build_judge_chain()
├── nodes/
│   ├── primary_classifier.py        PrimaryClassifierNode (LLM chain)
│   ├── second_opinion.py            SecondOpinionNode — per the BERT spec
│   ├── foreign_municipality.py      ForeignMunicipalityNode
│   ├── smells_risk.py               SmellsRiskNode (pure logic, no LLM)
│   ├── confidence_gate.py           ConfidenceGateNode (pure logic, no LLM)
│   ├── llm_judge.py                 LlmJudgeNode (LLM chain, conditional)
│   └── routing.py                   RoutingNode (Decision 8)
└── coordinator.py                   build_classification_coordinator(...)

config/classification.yaml           confidence_threshold, smell_review_risk_threshold,
                                      max_input_tokens, second_opinion_enabled,
                                      foreign_municipality_enabled, bert_model_path
                                      (all per the BERT spec) — this spec adds nothing new here

src/classiflow/api/routes/classification/
├── endpoints.py                     GET /classification/review-queue,
│                                     POST /classification/{job_id}/decision
└── schemas.py                       ClassificationDecisionRequest, ReviewQueueItem
```

## Config additions — `settings.py`

```python
CLASSIFICATION_MODEL_PATH: str = _DEFAULT_MODEL
JUDGE_MODEL_PATH: str = _DEFAULT_MODEL
DOCUMENT_STORAGE_ROOT: str = str(_PROJECT_ROOT / "storage" / "documents")
```

Same `UPPER_CASE` field + `classification_model_path` / `judge_model_path` /
`document_storage_root` lowercase property pattern already used throughout
`settings.py`.

`.gitignore` gains one entry alongside the existing `data/**`/`models/**` overrides:

```
storage/documents/**
```

## Testing

- Unit tests per node, mirroring `tests/enrichment/test_text_cleaner.py` /
  `tests/ingesta/test_node3.py`'s structure: `TestPrimaryClassifier` (using `MockLlm`),
  `TestSmellsRisk` and `TestConfidenceGate` (pure logic, table-driven over the weights
  and threshold branches), `TestLlmJudge` (`MockLlm`), `TestRoutingNode` (fake
  `IDocumentStorage`, asserts the right `subdirectory` for `accept` vs `human_review`).
- `TestLocalDiskStorage` — `save_staged` then `move_to_final` against a `tmp_path`,
  asserts the file exists at the expected final path and no longer at the staged path.
- Coordinator-level test: happy path (`accept`) writes a `ClassificationRecord` and a
  file under `classified/<label>/`; `human_review` path writes a record and a file under
  `review/human_review/`, then a follow-up call to the decision endpoint moves it to
  `classified/<label>/` and flips `human_overridden`.
- `PipelineService._run()` integration test: an accepted job with successful enrichment
  reaches `_run_classification`; a job that fails Stage 1-3 validation never gets staged
  (`save_staged` not called).

## Open items / risks

| Risk | Mitigation |
|---|---|
| A file staged after extraction but later rejected by node3/node4 is never cleaned up | Accepted — an orphaned staged file costs disk, not correctness; revisit with a retention sweep only if volume becomes real |
| `storage/documents/` grows unbounded over time (no retention policy) | Deferred deliberately — out of scope for this spec, revisit once real usage data exists |
| `LocalDiskStorage` is the only implementation ever exercised — the `IDocumentStorage` seam is unproven against a real blob backend | Accepted per explicit YAGNI decision; the Protocol boundary is what makes a future `AzureBlobStorage` additive rather than a rewrite, not a guarantee it will be painless |
| Deployment (Docker) needs a persistent volume for `storage/documents/`, not ephemeral container storage | Relevant to the already-deferred S4-T11 Docker task — noted here, not solved here |
| Gemma 4 GGUF/`llama-cpp-python` compatibility is a fast-moving target past this project's normal verification cadence | Confirm via the target GGUF's card + installed `llama-cpp-python` changelog before switching `CLASSIFICATION_MODEL_PATH`/`JUDGE_MODEL_PATH`, not assumed from this spec alone |

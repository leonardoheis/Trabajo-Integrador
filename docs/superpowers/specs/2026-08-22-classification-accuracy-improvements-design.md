# Classification Accuracy Improvements — Design

## Context

Stage 4 (Classification & Routing) is implemented and running against real municipal
documents (`feat/classification-routing`, not yet merged to `main`). Two full
end-to-end runs against an 18-document labeled sample (`playground/stage4/full_pipeline_end_to_end.ipynb`,
reports in `storage/reports/`) surfaced concrete, traced accuracy gaps:

- **Phi-4-mini-instruct** (the original primary classifier model) was directly observed
  fabricating evidence that does not exist in the source text (e.g. claiming a document
  "contains the phrase 'Compendio de Boletines'" when it does not appear anywhere in the
  excerpt). This was traced by reading the model's raw JSON `reasoning` field against the
  real `cleaned_text`, not inferred from the wrong label alone.
- Swapping the primary classifier to **Meta-Llama-3.1-8B-Instruct** (already applied —
  `Settings.CLASSIFICATION_MODEL_PATH`) measurably reduced this fabrication pattern (the
  document above is now correctly labeled `convenios`) but did **not** fix a separate,
  still-present bias toward defaulting to the generic `decretos` label under uncertainty,
  and did not fully resolve confusion between an institution-level pair
  (`resoluciones` vs. `resoluciones_concejo_municipal`, `decretos` vs.
  `decretos_concejo_municipal`) where the model identifies the right issuing body but
  picks the wrong sibling label.
- The `ConfidenceGateNode` → `LlmJudgeNode` tier, added in the original Stage 4 spec as a
  low-confidence tiebreaker, was traced (via direct code reading) to almost never fire in
  practice: `classifier_disagreement=True` routes straight to `HUMAN_REVIEW` today,
  bypassing the judge entirely — so the exact case where a second AI opinion would be
  most useful (two classifiers actively disagree) never reaches the one node built to
  reason about disagreement.
- The generated HTML report (`report_template.html`, filled in by
  `full_pipeline_end_to_end.ipynb`'s section 10) hardcodes "Phi-4-mini-instruct" as
  literal text in its masthead, left stale after the model swap.
- `EnrichedRecord` persists `cleaned_text` (post text-cleaning) but not the raw Stage 2
  extraction output; `Job.extracted_text` only persists raw text for non-accepted jobs
  (`PipelineService._finalize_job`'s existing `if final_status != "accepted"` gate) — so
  today, a successfully classified document's original extracted text is never durably
  stored anywhere.

This design covers five independent workstreams addressing these findings. Each touches
a disjoint set of files and can land as its own PR in any order.

## Goals

1. Fix the report template so it reflects whichever model `Settings` actually points at,
   not a hardcoded name.
2. Route `classifier_disagreement` cases to the LLM Judge instead of straight to human
   review, so a second, stronger LLM opinion is available to the human reviewer — without
   ever letting the judge bypass human review for a disagreement case.
3. Reduce the still-observed `resoluciones`/`resoluciones_concejo_municipal` and
   `decretos`/`decretos_concejo_municipal` sibling-pair confusion in the primary
   classifier's prompt, informed by direct tracing of the specific documents still
   failing after the Llama 3.1 8B swap.
4. Investigate whether OCR/extraction quality (DPI, language config) is a meaningful
   contributor to misclassification on older scanned documents, and produce a concrete
   recommendation — not a guaranteed code change.
5. Persist the raw, pre-cleaning Stage 2 extraction text for every accepted job, so it is
   available for future embedding/analysis work without needing to re-extract from the
   original file.

## Non-goals

- No new model swaps beyond the already-applied Llama 3.1 8B change.
- No new frontend/reviewer UI — the human-review flow stays API-only, as documented in
  the existing `full_pipeline_end_to_end.ipynb` and `POST /classification/{job_id}/decision`.
- No autonomous LLM-Judge accept/reject authority over a `classifier_disagreement` case.
  The judge is purely advisory in that path; only a human can move a disagreement case out
  of `human_review`.
- No embedding/semantic-search implementation for the newly-stored raw text — this design
  only makes the text durably available; consuming it is future work.
- No change to the existing low-confidence-no-disagreement judge path's auto-accept
  behavior (unchanged from the original Stage 4 spec).

## Decision 1 — Report model label reflects real Settings

**Problem**: `report_template.html`'s masthead paragraph and meta-row contain the literal
string "Phi-4-mini-instruct" and "Gemma 4", written once when the template was authored.
The notebook's report-generation cell (`full_pipeline_end_to_end.ipynb`, section 10)
never reads `Settings` for this — the string is static.

**Decision**: the notebook's report-generation cell reads `Settings.CLASSIFICATION_MODEL_PATH`
and `Settings.JUDGE_MODEL_PATH` at generation time, extracts each file's basename (e.g.
`Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf` → `Meta-Llama-3.1-8B-Instruct`), and substitutes
them into the report via the same `__TOKEN__` replacement mechanism the template already
uses for every other dynamic value (`__CORRECT__`, `__TOTAL__`, etc.). Two new tokens:
`__PRIMARY_MODEL_NAME__`, `__JUDGE_MODEL_NAME__`.

## Decision 2 — LLM Judge becomes an advisory second opinion for disagreement cases

### Current behavior (traced from `confidence_gate.py`)

```python
def decide(self, *, confidence, foreign_municipality, classifier_disagreement) -> ReviewRoute:
    if foreign_municipality is not None or classifier_disagreement:
        return ReviewRoute.HUMAN_REVIEW
    if confidence >= self.config.confidence_threshold:
        return ReviewRoute.ACCEPT
    return ReviewRoute.LLM_JUDGE
```

`classifier_disagreement` and `foreign_municipality` are both folded into the same
branch, and both skip the judge. In every real run so far, high-confidence documents
(0.9+) either agree (→ `ACCEPT`) or disagree (→ `HUMAN_REVIEW` directly) — the
`LLM_JUDGE` branch (low confidence, no disagreement) essentially never fires on real
data, since the primary classifier reports confidence ≥ 0.9 on nearly every document
regardless of correctness.

### New behavior

```python
def decide(self, *, confidence, foreign_municipality, classifier_disagreement) -> ReviewRoute:
    if foreign_municipality is not None:
        return ReviewRoute.HUMAN_REVIEW
    if classifier_disagreement:
        return ReviewRoute.LLM_JUDGE
    if confidence >= self.config.confidence_threshold:
        return ReviewRoute.ACCEPT
    return ReviewRoute.LLM_JUDGE
```

`foreign_municipality` keeps its own unconditional override — whether a document is even
from the right municipality is not something an LLM judge should be trusted to overrule,
so it goes straight to a human exactly as today. `classifier_disagreement` now reaches
the judge instead of bypassing it.

**Critical constraint, restated precisely**: reaching the judge via the
`classifier_disagreement` path never results in `ReviewRoute.ACCEPT`. The judge's
verdict is captured as data on the `ClassificationRecord` for the human reviewer to see,
but the coordinator's `_llm_judge` closure hard-codes `review_route = HUMAN_REVIEW`
whenever `classifier_disagreement` was the reason the judge ran — never derives the route
from `JudgeOutput.accept`. This is a deliberate, permanent asymmetry from the existing
low-confidence-no-disagreement path (where `accept=True` today does still route to
`ACCEPT`, unchanged) — disagreement is judged to be a strictly higher-risk situation than
low confidence alone, and this design does not relax that.

### `ClassificationState` / `ClassificationUpdate` needs to know *why* the judge ran

`_route_after_gate` currently only inspects `state["review_route"] == ReviewRoute.LLM_JUDGE`
to decide whether to visit the `llm_judge` node — it has no memory of *which* condition
sent it there. Since the judge's post-run routing decision now differs by reason
(disagreement → always `HUMAN_REVIEW`; low-confidence-no-disagreement → `accept`-derived,
as today), the state needs to carry the routing reason forward.

**Decision**: reuse the already-present `classifier_disagreement: bool` field on
`ClassificationState` (set by `_second_opinion`'s closure) as that signal — the
`_llm_judge` closure reads `state.get("classifier_disagreement", False)` directly; no new
state field needed. If `classifier_disagreement` is `True` when `_llm_judge` runs, the
route is hard-coded to `HUMAN_REVIEW` regardless of `JudgeOutput.accept`; otherwise the
existing `accept`-derived logic applies unchanged.

### `JudgeOutput` gains `final_label`

```python
class JudgeOutput(BaseEntity):
    accept: bool
    final_label: str  # NEW -- see below
    reasoning: str = ""
```

`final_label` is constrained by the prompt (not by post-hoc validation logic — see below)
to be exactly one of two strings: `primary_label` or `second_opinion_label` (both already
passed into `JudgeInput`), whichever the judge concludes the document text actually
supports. The judge never proposes a third label outside these two candidates — this
keeps the arbitration bounded to "which of the two existing opinions is right," matching
the actual failure pattern traced this session (right institution, wrong sibling label;
never a wholesale invention of an unrelated tenth category during a disagreement case).

When the judge tier runs via the **low-confidence, no-disagreement** path (unchanged from
today), `second_opinion_label` may be `None` (BETO can be disabled, or the primary and
second opinion may already agree at low confidence) — in that case `final_label` simply
echoes `primary_label` back, and `accept`/`reasoning` retain their original meaning
exactly as implemented today.

### `JudgeInput` gains the full OOD/SVM signal set (not just `smells`/`risk_score`)

**Gap found while designing this**: `ClassificationState["ood_metrics"]` (an `OodMetrics`
object — Mahalanobis p-value, cosine z-score, kNN distance, TF-IDF cosine z-score, each
with its own calibration status, plus `in_distribution` and `OodMetrics.smells`, a list of
*OOD-specific* signal names derived purely from these statistical metrics) and
`state["svm_agrees_with_prediction"]`/`state["svm_scores"]` are already fully computed by
`_second_opinion` and already carried all the way to `RoutingInput`/`ClassificationRecord`
today. But `_llm_judge`'s closure never reads them — `JudgeInput` only receives the
coordinator's own separately-computed `smells: list[str]` from `SmellsRiskNode` (a
broader list mixing OOD-derived smells with non-OOD ones like `"unreadable_document"`,
`"classifier_disagreement"`, `"foreign_municipality"`) and `risk_score: int`, not the
underlying numeric OOD signals those smells were computed from. `OodMetrics.smells` and
`ClassificationState["smells"]` are two distinct, same-named-but-different lists — the
judge currently only sees the second, broader one, never the raw statistical evidence
`OodMetrics` itself carries.

**Decision**: `JudgeInput` gains two new fields:

```python
class JudgeInput(BaseEntity):
    cleaned_text: str
    primary_label: str
    primary_confidence: float
    second_opinion_label: str | None = None
    second_opinion_confidence: float | None = None  # NEW -- BETO's own confidence, not just its label
    ood_metrics: OodMetrics | None = None            # NEW -- the full object, not a flattened summary
    svm_agrees_with_prediction: bool = True          # NEW
    smells: list[str] = Field(default_factory=list)
    risk_score: int = 0
    foreign_municipality: str | None = None
```

`_llm_judge`'s coordinator closure passes `state.get("ood_metrics")`,
`state.get("svm_agrees_with_prediction", True)`, and
`state.get("second_opinion_confidence")` straight through — no new computation, purely
wiring already-present state into the judge's input, matching the pattern every other
`RoutingInput` field already follows.

### Judge prompt: interpreting the raw OOD/SVM signals, not just relaying them

Handing the judge raw floats (`cosine_z: -0.3552`, `mahalanobis_p_value: 0.484758`, ...)
with no interpretation guidance would just move the "which values mean trouble" judgment
call onto the LLM with no more grounding than it has today — these are calibrated
statistical signals, not self-explanatory numbers. `_format_prompt` in
`prompts/llm_judge.py` renders each metric alongside its own calibration status and a
plain-language interpretation derived from the metric's *actual semantics*, verified
against `bert/ood_scorer.py`/`ood_stats.py` (already read this session) rather than
guessed:

- **`mahalanobis_p_value`** (and its `_theoretical` counterpart): a p-value — **low**
  means anomalous/far from the training distribution for the predicted class, **high**
  (closer to the observed value here, `0.48`/`0.94`) means the document looks statistically
  typical for that class. Only trust this reading when `mahalanobis_calibration_status ==
  "calibrated"` — `"refused_degenerate"` (as in the example payload) means this specific
  model's calibration step couldn't produce a reliable p-value at all, and the prompt
  says so explicitly rather than silently treating a degenerate p-value as evidence.
- **`cosine_z` / `tfidf_cosine_z`**: z-scores — near 0 is typical, a large magnitude
  (either direction) is anomalous. `resolve_ood_thresholds`/`smell_thresholds.json`
  already define the exact cutoff each deployed BETO model uses for "anomalous" on this
  metric; the prompt states the metric's value **and** whether it crossed that specific
  model's own threshold (already computed into `OodMetrics.smells`), rather than asking
  the LLM to invent its own idea of "large."
- **`knn_distance`**: raw Euclidean distance in PCA-projected embedding space to the
  nearest same-class training examples — larger means less similar to anything BETO was
  actually trained on for that predicted class. Same calibrated-threshold framing as
  above.
- **`in_distribution`**: the single already-computed boolean summarizing whether *any*
  calibrated OOD signal fired — the prompt surfaces this as the headline interpretation,
  with the individual metrics as supporting detail, not the other way around.
- **`svm_agrees_with_prediction`**: BETO's own SVM reviewer's independent agreement/
  disagreement with BETO's primary softmax prediction — a same-model internal
  consistency check, distinct from the primary-vs-BETO cross-model disagreement that
  routed this case to the judge in the first place. The prompt explains this distinction
  explicitly, since it is easy to conflate the two different "disagreement" concepts.

This turns the judge's evidence base from "two label strings plus a risk number" into
"two labeled opinions plus the actual statistical grounds for trusting or distrusting
BETO's opinion specifically" — directly answering whether BETO's disagreement in this
particular case looks like a real signal (in-distribution, calibrated, SVM-consistent) or
noise (out-of-distribution, uncalibrated, internally inconsistent).

### New fields on `ClassificationRecord` / `RoutingInput`

```python
# database/models.py — ClassificationRecord
judge_final_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
judge_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
```

```python
# classification/domain/results.py — RoutingInput
judge_final_label: str | None = None
judge_reasoning: str | None = None
```

Populated only when `judged_by_llm=True` (mirroring the existing field's own gating).
These sit alongside the existing `label` (primary classifier's original label, unchanged —
the routing/human decision still operates on whatever `label` already means today) and
`second_opinion_label` — the human reviewer, pulling a record from
`GET /classification/review-queue`, now sees three independent opinions
(`label`, `second_opinion_label`, `judge_final_label`) plus the judge's one-sentence
`judge_reasoning`, and still makes the final call via the unchanged
`POST /classification/{job_id}/decision` endpoint. `label` itself is **not** overwritten
by the judge's verdict — the judge's opinion is additive metadata, never a silent label
change.

### Judge prompt addition (`prompts/llm_judge.py`)

The existing `_TEMPLATE` already receives `second_opinion_label`, `smells`, `risk_score`,
and reasons about disagreement in its ACCEPT/HUMAN_REVIEW instructions. One new
instruction block, conditioned on disagreement actually being present in the input (i.e.
`second_opinion_label is not None and second_opinion_label != primary_label`):

> When the primary and second-opinion labels disagree, decide which one the document
> text actually supports using the category anchors above, and return that exact label
> string as `final_label` — never a different category, even if you believe neither
> candidate is fully correct. If the text is genuinely ambiguous between the two, still
> pick the more likely candidate (the same "if genuinely torn" tie-breaking rule the
> primary classifier itself follows) and reflect the uncertainty in `reasoning`, not by
> refusing to choose.

`_extract()`'s existing JSON-object regex extraction needs no change — `final_label` is
just one more string field in the same flat JSON object `accept`/`reasoning` already are.

## Decision 3 — Concejo-municipal sibling-pair prompt tuning, scoped precisely

**What "informed by direct tracing" means, concretely**: before writing any prompt
change, run the same diagnostic technique used repeatedly this session against the two
still-failing rows from the latest (Llama 3.1 8B) report:

- `resolucion_cm_16879_2024.pdf` — expected `resoluciones_concejo_municipal`, got
  `decretos` (BETO's own second opinion correctly said `resolucion_concejo_municipal`,
  0.996 confidence — the primary classifier disagreed with a confident, correct second
  opinion).
- `resolucion_cm_197_2024.pdf` — expected `resoluciones_concejo_municipal`, got
  `resoluciones` (right act type, wrong issuing body — the "sibling" failure specifically).

For each: pull the real `cleaned_text` from `data/classiflow.db` via direct SQL
(`select(EnrichedRecord).where(job_id == ...)`, the same pattern used throughout this
session), invoke `build_classification_chain` directly with `temperature=0.0` (bypassing
the pipeline's default sampling temperature for reproducibility during diagnosis only —
production temperature is untouched), and read the model's raw JSON `reasoning` field
verbatim. This tells us *which specific textual signal* the model weighted incorrectly
(analogous to how the Concejo-override hallucination and the `compendios_de_boletines`
fabrication were both found earlier — by reading the model's own stated reasoning against
the ground-truth text, not by guessing from the wrong label alone).

Only after that trace produces a concrete finding does the task make **one** targeted
edit to `_TEMPLATE`'s `Rules:` block or `_CATEGORY_DEFS`'s per-category definitions in
`primary_classification.py` — not a speculative rewrite of the whole prompt. The edit is
then validated against:
- Both currently-failing rows (must flip to correct, or at minimum stop being
  hallucinated/uncaught wrong).
- A representative sample of currently-**passing** rows, especially the ones already
  fixed by the earlier Concejo-override rule this session
  (`decreto_cm_10554_1995.pdf`, `decreto_cm_1016_2025.pdf`) and the plain `decretos`/
  `resoluciones` cases (`decreto_1000_2008.pdf`, `resolucion_100_2020.pdf`) — to confirm
  no regression, using the same direct single-document invocation harness (not a full
  pipeline run) for fast iteration.

This decision does not commit to a specific prompt wording in advance — the actual
wording is a plan-time (or even task-execution-time) decision, contingent on what the
trace in this task actually reveals. This mirrors how the earlier Concejo-override rule
and the `compendios_de_boletines` tightening were both developed this session: trace
first, then write one precise rule, then validate.

## Decision 4 — OCR/extraction quality investigation

**Scope**: read-only investigation producing a written finding and recommendation; no
guaranteed code change lands in this design as a result. If the investigation finds a
clear, low-risk win (e.g. raising `OCR_RENDER_DPI`), a follow-up task applies it and
re-validates; if the investigation is inconclusive or the fix is invasive, it's deferred
as a separate, explicitly-scoped follow-up.

**Already known from this session's tracing** (see `extractors/ocr.py`,
`settings.py`): OCR runs via `easyocr` (`Settings.OCR_LANG`, default `"es"`) over pages
rendered by `pymupdf` at `Settings.OCR_RENDER_DPI` (default `200`). MarkItDown is tried
first (`extractors/markitdown.py`); OCR is the fallback for scanned/image-only PDFs.
`ExtractionResult.extractor_used` records which path a given document took.

**Investigation steps**:
1. For the three worst-OCR real documents already identified this session
   (`declaracion_2501_1991.pdf`, `decreto_ordenanza_1182_1976.pdf`, and
   `decreto_ordenanza_1314_1980.pdf` — the one that was misdetected as Esperanto and
   held at `node3_content_validation`), confirm via `extractor_used` that they actually
   went through the OCR path (not MarkItDown) rather than assuming it.
2. Re-run OCR extraction directly (bypassing the full pipeline) against each of the three
   at a higher DPI (e.g. 300, 400) and compare the resulting text's legibility
   side-by-side against the current 200 DPI output — same technique as this session's
   direct-invocation diagnostics elsewhere, applied to the extraction layer instead of
   the classifier.
3. Check whether `easyocr`'s language configuration (`Settings.OCR_LANG = "es"`) is
   actually the right single-language hint for documents this old, or whether allowing a
   broader language set changes recognition quality — the `decreto_ordenanza_1314_1980.pdf`
   Esperanto misdetection happened at the *language-detection* stage (Lingua, in
   `node3_content_validation.py`), not OCR itself, so this check clarifies whether that's
   a downstream symptom of poor OCR output or an independent language-detector weakness.
4. Write up findings: does DPI materially change output quality for these documents; is
   the language configuration a contributing factor; is there a clear, low-risk
   recommendation, or does the corpus's OCR quality require a different tool/approach
   entirely (out of scope to solve here, but worth naming if that's the actual
   conclusion).

## Decision 5 — Persist raw Stage 2 extraction text on `EnrichedRecord`

**Problem, precisely**: `PipelineService._run_enrichment` (lines 157–196) already has
`final_state["text"]` (Stage 2's raw extraction output, pre-cleaning) in scope when it
constructs `EnrichedRecord(job_id=..., cleaned_text=result["cleaned_text"], ...)` — the
raw text is right there, in the same method, but never captured on the record.
Separately, `Job.extracted_text` (via `_finalize_job`) only ever persists raw text when
`final_status != "accepted"` — so for the (common, successful) accepted-job case, no raw
extraction text survives anywhere in the database once the job completes.

**Decision**: add `raw_text: Mapped[str] = mapped_column(Text, nullable=True)` to
`EnrichedRecord` (nullable, since a migration can't backfill historical rows). Populate
it in `_run_enrichment`'s existing `EnrichedRecord(...)` construction from
`final_state["text"]`, alongside `cleaned_text`. This runs for every accepted job — no
new gating condition, since the explicit goal is availability for future embedding work,
which needs the success-path text, not just the failure-path text `Job.extracted_text`
already covers.

No embedding, indexing, or vector-store work is included here — this decision only makes
the raw text durably queryable (`select(EnrichedRecord.raw_text).where(...)`) for
whatever future embedding pipeline consumes it.

## Testing strategy

- **Decision 1**: unit test asserting the report-generation cell's token substitution
  produces the real `Settings` basename, not the old literal string (playground code —
  covered by the notebook's own JSON-validation convention, not `tests/`, since
  `playground/` is mypy/pytest-excluded per `pyproject.toml`).
- **Decision 2**: `tests/classification/test_confidence_gate_node.py`
  (extended) — `decide()` returns `LLM_JUDGE` for `classifier_disagreement=True`
  (currently asserts `HUMAN_REVIEW`, needs updating). `tests/classification/test_coordinator.py`
  extended with a case where `classifier_disagreement=True` and the judge is invoked,
  asserting the final `review_route` is `HUMAN_REVIEW` regardless of the mocked judge's
  `accept` value, and asserting `JudgeInput` actually receives `state["ood_metrics"]`/
  `state["svm_agrees_with_prediction"]`/`state["second_opinion_confidence"]` (not just
  `smells`/`risk_score`) via a spy/mock judge chain. `tests/classification/test_llm_judge_node.py`/
  `test_llm_judge_chain.py` extended for `final_label` parsing and for the new
  `ood_metrics`/`svm_agrees_with_prediction`/`second_opinion_confidence` fields rendering
  correctly into the prompt (including the calibration-status-gated interpretation text —
  a `"refused_degenerate"` Mahalanobis status must not render as if it were a trustworthy
  p-value). `tests/classification/test_routing_node.py` extended to confirm
  `judge_final_label`/`judge_reasoning` persist correctly on `ClassificationRecord`.
- **Decision 3**: no new automated test beyond the existing `test_primary_classification_chain.py`
  suite (which already exercises `_extract`/`build_classification_chain` against
  `MockLlm`) — the actual validation for this decision is the direct real-model tracing
  described above, run manually against the real corpus, not a mocked unit test (mirrors
  how the earlier Concejo-override rule was validated this session).
- **Decision 4**: no automated test — this is a research task producing a written
  finding, not a code change with its own test suite (unless the follow-up DPI change
  actually lands, in which case it gets its own coverage at that time).
- **Decision 5**: `tests/shared/test_pipeline_service_enrichment.py` extended to assert
  `EnrichedRecord.raw_text` is populated on the happy path. New alembic migration
  (`00XX_add_enriched_record_raw_text.py`) with `upgrade()`/`downgrade()`, following the
  exact pattern of `0004_add_enriched_records.py`.

## Open questions for the plan

- Exact migration revision number (depends on what else lands on `main`/this branch
  before this work starts).
- Whether `judge_final_label`/`judge_reasoning` need their own `ReviewQueueItem`/API
  schema exposure (`api/routes/classification/schemas.py`) so
  `GET /classification/review-queue` actually surfaces them to a caller, or whether
  that's assumed as part of this same PR — the design intends the fields to be visible to
  a reviewer, so schema exposure is in scope, but the plan should make this an explicit
  task rather than an implicit side effect.

# Classification Accuracy Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five traced accuracy/observability gaps in Stage 4 classification: a
stale model name in the HTML report, the LLM Judge never running on disagreement
cases, sibling-pair label confusion in the primary classifier's prompt, an OCR
quality investigation, and durable storage of raw pre-cleaning extraction text.

**Architecture:** Five independent workstreams, each touching a disjoint file set.
Decision 2 (Judge-as-arbiter) is the only one with real cross-file plumbing —
`ConfidenceGateNode` → `ClassificationState`/coordinator closures → `JudgeInput`/
`JudgeOutput` → `ClassificationRecord`/`RoutingInput` → API schema. Decisions 1, 3,
4, 5 are self-contained.

**Tech Stack:** Python 3.10, LangGraph (`StateGraph`), LangChain (`Runnable` chains),
Pydantic v2 (`BaseEntity`), SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Alembic,
pytest, Jupyter (`playground/stage4/full_pipeline_end_to_end.ipynb`).

**Spec:** `docs/superpowers/specs/2026-08-22-classification-accuracy-improvements-design.md`

## Global Constraints

- Line length 100, double quotes, mypy strict (`src/` only) — `uv run poe check` after
  every task.
- Never use `Any`, `from __future__ import annotations`, or `TYPE_CHECKING` unless a
  real circular import forces it.
- Domain/value objects use `BaseEntity` (`classiflow.domain.base.BaseEntity`); services
  use plain `__init__`.
- Custom exceptions: `@dataclass` subclasses of a plain base in each service's own
  `exceptions.py`, `__post_init__` calling `super().__init__(str(self))`.
- Never commit/push/PR without the user's explicit per-message authorization — this
  plan only edits the working tree.
- **Critical, non-negotiable invariant for every Decision-2 task**: a
  `classifier_disagreement=True` case must NEVER reach `ReviewRoute.ACCEPT`. The
  judge's verdict on a disagreement case is advisory data only; the route is always
  hard-coded to `HUMAN_REVIEW`. Every task and test touching this path re-asserts this.

---

## Task 1: Report reflects the real configured model names (Decision 1)

**Files:**
- Modify: `src/classiflow/playground/stage4/report_template.html:400`
- Modify: `src/classiflow/playground/stage4/full_pipeline_end_to_end.ipynb` (the
  report-generation cell containing `_substitutions = {...}`, currently ending with
  `"__HELD_FINDING_TEXT__": _held_finding_text,`)

**Interfaces:**
- Consumes: `Settings.classification_model_path`, `Settings.judge_model_path`
  (`src/classiflow/settings.py:135-144`) — both already-existing properties, no
  Settings change needed.
- Produces: two new template tokens, `__PRIMARY_MODEL_NAME__` and
  `__JUDGE_MODEL_NAME__`, substituted the same way every other token in that cell
  already is.

- [x] **Step 1: Replace the hardcoded model names in the template**

In `report_template.html`, line 400 currently reads:
```html
<span>Model: <b>Phi-4-mini-instruct</b> (primary) &middot; <b>BETO v2</b> (second opinion)</span>
```
Change it to:
```html
<span>Model: <b>__PRIMARY_MODEL_NAME__</b> (primary) &middot; <b>BETO v2</b> (second opinion) &middot; <b>__JUDGE_MODEL_NAME__</b> (judge)</span>
```
(BETO v2 stays literal — it is not read from `Settings`, there is no settings path
for it; only the two GGUF model names are dynamic.)

- [x] **Step 2: Compute the two model names in the notebook's report cell**

In the report-generation cell (the one building `_substitutions`), add before the
`_substitutions = {...}` line:
```python
def _model_display_name(model_path: str) -> str:
    return Path(model_path).stem


_primary_model_name = _model_display_name(Settings.classification_model_path)
_judge_model_name = _model_display_name(Settings.judge_model_path)
```
`Path(...).stem` on `.../Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf` yields
`Meta-Llama-3.1-8B-Instruct-Q4_K_M` — acceptable as-is (matches the file's actual
name; no further parsing needed since this is just a report label, not something
programs compare against). Add the import if `Settings` is not already imported in
this notebook's earlier cells — check with a preceding cell read; `classiflow.settings`
is almost certainly already imported earlier in the notebook (it drives model paths
elsewhere), so this step may be a no-op beyond adding the two lines above.

- [x] **Step 3: Add the two new tokens to `_substitutions`**

```python
_substitutions = {
    "__INTRO_TEXT__": _intro_text,
    "__GENERATED_AT__": _generated_at,
    "__TOTAL__": str(_total),
    "__CORRECT__": str(_correct),
    "__WRONG_CAUGHT__": str(len(_wrong_caught)),
    "__WRONG_UNCAUGHT__": str(len(_wrong_uncaught)),
    "__HELD_EARLIER__": str(len(_held_earlier)),
    "__CRASHED__": str(len(_crashed)),
    "__TABLE_INTRO_TEXT__": _table_intro_text,
    "__ROWS_HTML__": _rows_html,
    "__CAUGHT_FINDING_TEXT__": _caught_finding_text,
    "__UNCAUGHT_FINDING_TEXT__": _uncaught_finding_text,
    "__HELD_FINDING_TEXT__": _held_finding_text,
    "__PRIMARY_MODEL_NAME__": _primary_model_name,
    "__JUDGE_MODEL_NAME__": _judge_model_name,
}
```

- [x] **Step 4: Hand the notebook re-run command to the user**

Per this project's execution-workflow rule, do not run the notebook yourself. Hand
over:
```
uv run jupyter execute src/classiflow/playground/stage4/full_pipeline_end_to_end.ipynb
```
Ask the user to confirm the generated report under `storage/reports/` shows the real
model names in its masthead (e.g. `Meta-Llama-3.1-8B-Instruct-Q4_K_M` instead of
`Phi-4-mini-instruct`) instead of running it yourself.

- [x] **Step 5: Commit**

Committed as `5bf2602` — "feat: enhance model configuration and reporting" (bundled
with the `pyproject.toml`/`.pre-commit-config.yaml` `models/` exclusion fixes from
the same working session).

---

## Task 2: `ConfidenceGateNode.decide()` routes disagreement to the judge

**Files:**
- Modify: `src/classiflow/classification/nodes/confidence_gate.py:59-70`
- Test: `tests/classification/test_confidence_gate_node.py`

**Interfaces:**
- Consumes: nothing new — same `confidence: float`, `foreign_municipality: str | None`,
  `classifier_disagreement: bool` signature.
- Produces: `ReviewRoute` — `foreign_municipality is not None` still always wins
  (`HUMAN_REVIEW`); `classifier_disagreement` now yields `LLM_JUDGE` instead of
  `HUMAN_REVIEW`.

- [ ] **Step 1: Update the existing disagreement test to expect `llm_judge`**

In `tests/classification/test_confidence_gate_node.py`, replace:
```python
def test_classifier_disagreement_routes_to_human_review_regardless_of_confidence(self) -> None:
    route = _node().decide(confidence=0.99, foreign_municipality=None, classifier_disagreement=True)
    assert route == "human_review"
```
with:
```python
def test_classifier_disagreement_routes_to_llm_judge_regardless_of_confidence(self) -> None:
    route = _node().decide(confidence=0.99, foreign_municipality=None, classifier_disagreement=True)
    assert route == "llm_judge"
```

- [ ] **Step 2: Add a test asserting `foreign_municipality` still overrides even when disagreement is also set**

Add to `TestConfidenceGateDecide`:
```python
    def test_foreign_municipality_wins_over_disagreement(self) -> None:
        route = _node().decide(
            confidence=0.99, foreign_municipality="Cordoba", classifier_disagreement=True
        )
        assert route == "human_review"
```

- [ ] **Step 3: Run the tests to verify they fail against current code**

Run: `uv run pytest tests/classification/test_confidence_gate_node.py -v`
Expected: `test_classifier_disagreement_routes_to_llm_judge_regardless_of_confidence`
FAILs (`decide()` still returns `human_review`); the new override test PASSes already
(current code also returns `human_review` for that combination, coincidentally the
same as the new expectation).

- [ ] **Step 4: Update `decide()`**

Replace:
```python
    def decide(
        self,
        *,
        confidence: float,
        foreign_municipality: str | None,
        classifier_disagreement: bool,
    ) -> ReviewRoute:
        if foreign_municipality is not None or classifier_disagreement:
            return ReviewRoute.HUMAN_REVIEW
        if confidence >= self.config.confidence_threshold:
            return ReviewRoute.ACCEPT
        return ReviewRoute.LLM_JUDGE
```
with:
```python
    def decide(
        self,
        *,
        confidence: float,
        foreign_municipality: str | None,
        classifier_disagreement: bool,
    ) -> ReviewRoute:
        if foreign_municipality is not None:
            return ReviewRoute.HUMAN_REVIEW
        if classifier_disagreement:
            return ReviewRoute.LLM_JUDGE
        if confidence >= self.config.confidence_threshold:
            return ReviewRoute.ACCEPT
        return ReviewRoute.LLM_JUDGE
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/classification/test_confidence_gate_node.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/classiflow/classification/nodes/confidence_gate.py tests/classification/test_confidence_gate_node.py
git commit -m "feat: route classifier disagreement to the LLM judge instead of straight to human review"
```

---

## Task 3: `JudgeOutput` gains `final_label`; judge prompt gains disagreement-arbitration instructions

**Files:**
- Modify: `src/classiflow/classification/domain/results.py:13-15`
- Modify: `src/classiflow/classification/prompts/llm_judge.py`
- Test: `tests/classification/test_llm_judge_chain.py`

**Interfaces:**
- Consumes: `JudgeInput` (unchanged in this task — see Task 4 for its new fields).
- Produces: `JudgeOutput.final_label: str` — every existing and future caller of
  `build_judge_chain(...).invoke(...)` now gets this field back.

- [ ] **Step 1: Write the failing test for `final_label` echoing `primary_label` when no disagreement**

Add to `tests/classification/test_llm_judge_chain.py`:
```python
_ACCEPT_WITH_LABEL_RESPONSE = (
    '{"accept": true, "final_label": "ordenanzas", '
    '"reasoning": "label matches the document content"}'
)


class TestBuildJudgeChainFinalLabel:
    def test_parses_final_label_field(self) -> None:
        chain = build_judge_chain(MockLlm(response=_ACCEPT_WITH_LABEL_RESPONSE))
        output = chain.invoke(_input())
        assert output.final_label == "ordenanzas"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/classification/test_llm_judge_chain.py -v`
Expected: FAIL — `JudgeOutput` has no `final_label` field, `model_validate` raises
`ValidationError` (extra fields are dropped by default in Pydantic unless the model
requires it — since `final_label` will be a required field once added, the CURRENT
model has no such field so the JSON key is simply ignored today; the test fails
because `output.final_label` raises `AttributeError` — confirms the field doesn't
exist yet).

- [ ] **Step 3: Add `final_label` to `JudgeOutput`**

In `src/classiflow/classification/domain/results.py`, replace:
```python
class JudgeOutput(BaseEntity):
    accept: bool
    reasoning: str = ""
```
with:
```python
class JudgeOutput(BaseEntity):
    accept: bool
    final_label: str
    reasoning: str = ""
```

- [ ] **Step 4: Update the two existing `_VALID_RESPONSE` fixtures that now fail validation**

`final_label` is a new required field with no default — every existing test JSON
fixture that omits it will now fail `model_validate`. Update:

`tests/classification/test_llm_judge_chain.py`:
```python
_VALID_RESPONSE = (
    '{"accept": true, "final_label": "ordenanzas", '
    '"reasoning": "label matches the document content"}'
)
```

`tests/classification/test_llm_judge_node.py`:
```python
_VALID_RESPONSE = (
    '{"accept": false, "final_label": "resoluciones_concejo_municipal", '
    '"reasoning": "second opinion strongly disagrees"}'
)
```

`tests/classification/test_coordinator.py`:
```python
_JUDGE_ACCEPT_RESPONSE = '{"accept": true, "final_label": "ordenanzas", "reasoning": "confirmed"}'
```

`tests/shared/test_pipeline_service_enrichment.py` and
`tests/shared/test_pipeline_service_classification.py` (check this second file for
the same `_JUDGE_ACCEPT_RESPONSE`-shaped literal — grep
`'"accept": true, "reasoning"'` across `tests/` to find every remaining occurrence and
update each the same way, adding a `"final_label": "<any label present in that test's
own primary_label fixture>"` key).

- [ ] **Step 5: Run the full test suite to confirm no other JSON fixture was missed**

Run: `uv run pytest tests/classification/ tests/shared/ -v`
Expected: any remaining `ValidationError: final_label Field required` failures point
to a fixture still missing the key — fix each the same way, then re-run until clean.

- [ ] **Step 6: Add the disagreement-arbitration instruction block to the judge prompt**

In `src/classiflow/classification/prompts/llm_judge.py`, update `_TEMPLATE` (adding
the new instruction paragraph and the `final_label` field to the JSON contract):
```python
_TEMPLATE = """\
Task: you are the final quality gate for the Municipalidad de Rosario's automated \
document classification pipeline. A primary classifier assigned a label but was not \
confident enough to auto-accept, or a second opinion disagreed with it. Decide ACCEPT \
(the label is correct, safe to finalize) or HUMAN_REVIEW (send to a person), and state \
which label the evidence actually supports as final_label.

Category anchors -- what the text for each label should actually contain:
{category_anchors}

Primary classifier's label: {primary_label} (confidence: {primary_confidence})
Second opinion label (independent model, "none" if disabled): {second_opinion_label}
Automated risk signals (heuristic, not verified against the text -- treat as a \
caution flag, not a verdict): smells={smells}, risk_score={risk_score}
Foreign municipality detected: {foreign_municipality}

Decide HUMAN_REVIEW, not ACCEPT, when any of these hold:
- foreign_municipality is not "none" -- the document may not even be from \
Municipalidad de Rosario, which no amount of label-matching fixes.
- the document text does not clearly match the anchor for {primary_label} above.
- second_opinion_label disagrees with the primary label AND you cannot tell from \
the text which of the two is actually correct.
Otherwise, a high risk_score or a non-empty smells list is a reason for caution -- \
mention it in your reasoning -- but not by itself a reason to override a label the \
text clearly supports.

When the primary and second-opinion labels disagree, decide which one the document \
text actually supports using the category anchors above, and return that exact label \
string as final_label -- never a different category, even if you believe neither \
candidate is fully correct. If the text is genuinely ambiguous between the two, still \
pick the more likely candidate and reflect the uncertainty in reasoning, not by \
refusing to choose. If second_opinion_label is "none" or matches the primary label, \
final_label is simply {primary_label}.

Document text: {cleaned_text}

Answer with a single JSON object and nothing else.

JSON:
{{"accept": "true or false -- true means the primary label is correct and safe to accept", \
"final_label": "the label the evidence actually supports -- must be exactly {primary_label} \
or {second_opinion_label}, never a third category", \
"reasoning": "one short sentence citing the specific evidence -- textual or signal-based -- \
behind your decision"}}"""
```

- [ ] **Step 7: Run tests again to confirm everything passes**

Run: `uv run pytest tests/classification/ tests/shared/ -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/classiflow/classification/domain/results.py src/classiflow/classification/prompts/llm_judge.py tests/classification/test_llm_judge_chain.py tests/classification/test_llm_judge_node.py tests/classification/test_coordinator.py tests/shared/test_pipeline_service_enrichment.py tests/shared/test_pipeline_service_classification.py
git commit -m "feat: LLM judge output includes final_label, arbitrating primary vs second-opinion disagreement"
```

---

## Task 4: `JudgeInput` gains OOD/SVM signal fields; judge prompt interprets them

**Files:**
- Modify: `src/classiflow/classification/prompts/llm_judge.py`
- Test: `tests/classification/test_llm_judge_chain.py`

**Interfaces:**
- Consumes: `OodMetrics` (`src/classiflow/classification/bert/ood_scorer.py:42-55`) —
  `mahalanobis_p_value: float`, `mahalanobis_p_value_theoretical: float`,
  `cosine_z: float`, `knn_distance: float`, `tfidf_cosine_z: float | None`,
  `in_distribution: bool`, `mahalanobis_calibration_status: Literal["calibrated",
  "not_calibrated", "refused_degenerate"]`, `cosine_calibration_status: Literal
  ["calibrated", "not_calibrated"]`, `knn_distance_calibration_status: Literal
  ["calibrated", "not_calibrated"]`, `tfidf_calibration_status: Literal["calibrated",
  "not_calibrated"] | None`.
- Produces: `JudgeInput.second_opinion_confidence: float | None`,
  `JudgeInput.ood_metrics: OodMetrics | None`,
  `JudgeInput.svm_agrees_with_prediction: bool` — Task 5's coordinator wiring passes
  these through from `ClassificationState`.

- [ ] **Step 1: Write the failing test for the new fields rendering into the prompt**

Add to `tests/classification/test_llm_judge_chain.py`:
```python
from classiflow.classification.bert.ood_scorer import OodMetrics


def _ood_metrics(**overrides: object) -> OodMetrics:
    defaults: dict[str, object] = {
        "mahalanobis_p_value": 0.484758,
        "mahalanobis_p_value_theoretical": 0.94,
        "cosine_z": -0.3552,
        "knn_distance": 12.4,
        "in_distribution": True,
        "mahalanobis_calibration_status": "refused_degenerate",
    }
    defaults.update(overrides)
    return OodMetrics.model_validate(defaults)


class TestFormatPromptOodSignals:
    def test_degenerate_mahalanobis_status_is_flagged_not_silently_trusted(self) -> None:
        chain_input = _input(
            second_opinion_label="resoluciones",
            second_opinion_confidence=0.996,
            ood_metrics=_ood_metrics(),
            svm_agrees_with_prediction=False,
        )
        prompt = _format_prompt(chain_input)
        assert "refused_degenerate" in prompt
        assert "0.484758" in prompt

    def test_in_distribution_and_svm_agreement_both_render(self) -> None:
        chain_input = _input(
            second_opinion_label="resoluciones",
            second_opinion_confidence=0.996,
            ood_metrics=_ood_metrics(in_distribution=False),
            svm_agrees_with_prediction=False,
        )
        prompt = _format_prompt(chain_input)
        assert "in_distribution: False" in prompt or "not in-distribution" in prompt.lower()
        assert "svm" in prompt.lower()
```
Import `_format_prompt` (already a module-level function in `llm_judge.py`, add it
to this test file's existing `from classiflow.classification.prompts.llm_judge
import JudgeInput, build_judge_chain` line as `_format_prompt` too — it's a private
name but this test file already lives in the same conceptual unit and other test
files in this codebase (e.g. `test_primary_classification_chain.py`, referenced in
the spec) follow the same pattern of testing private formatting functions directly).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/classification/test_llm_judge_chain.py -v`
Expected: FAIL — `JudgeInput` has no `ood_metrics`/`svm_agrees_with_prediction`/
`second_opinion_confidence` fields yet (`ValidationError` on unexpected... actually
Pydantic silently ignores unknown kwargs passed to `model_validate` with a dict
unless `extra="forbid"`; check `BaseEntity`'s `model_config` — it has no `extra`
setting, so Pydantic's own default `extra="ignore"` applies, meaning the test fails
not on construction but on the assertion that the new content actually appears in
the rendered prompt, since `_format_prompt` doesn't reference these fields yet).

- [ ] **Step 3: Add the new fields to `JudgeInput`**

In `src/classiflow/classification/prompts/llm_judge.py`, replace:
```python
class JudgeInput(BaseEntity):
    cleaned_text: str  # full, untruncated -- unlike PrimaryClassificationInput
    primary_label: str
    primary_confidence: float
    second_opinion_label: str | None = None
    smells: list[str] = Field(default_factory=list)
    risk_score: int = 0
    foreign_municipality: str | None = None
```
with:
```python
class JudgeInput(BaseEntity):
    cleaned_text: str  # full, untruncated -- unlike PrimaryClassificationInput
    primary_label: str
    primary_confidence: float
    second_opinion_label: str | None = None
    second_opinion_confidence: float | None = None
    ood_metrics: OodMetrics | None = None
    svm_agrees_with_prediction: bool = True
    smells: list[str] = Field(default_factory=list)
    risk_score: int = 0
    foreign_municipality: str | None = None
```
Add the import at the top of the file:
```python
from classiflow.classification.bert.ood_scorer import OodMetrics
```

- [ ] **Step 4: Add an OOD-signal interpretation block to `_TEMPLATE` and render it in `_format_prompt`**

Add a new template section (insert after the existing `Automated risk signals` /
`Foreign municipality detected` lines, before the `Decide HUMAN_REVIEW` block):
```python
_TEMPLATE = """\
Task: you are the final quality gate for the Municipalidad de Rosario's automated \
document classification pipeline. A primary classifier assigned a label but was not \
confident enough to auto-accept, or a second opinion disagreed with it. Decide ACCEPT \
(the label is correct, safe to finalize) or HUMAN_REVIEW (send to a person), and state \
which label the evidence actually supports as final_label.

Category anchors -- what the text for each label should actually contain:
{category_anchors}

Primary classifier's label: {primary_label} (confidence: {primary_confidence})
Second opinion label (independent model, "none" if disabled): {second_opinion_label} \
(confidence: {second_opinion_confidence})
Automated risk signals (heuristic, not verified against the text -- treat as a \
caution flag, not a verdict): smells={smells}, risk_score={risk_score}
Foreign municipality detected: {foreign_municipality}

Second opinion's own statistical grounding (how much to trust ITS disagreement, \
distinct from whether it agrees with the primary label):
{ood_signal_block}
SVM reviewer agreement with second opinion's own predicted label (a same-model \
internal consistency check on the second opinion, NOT the primary-vs-second-opinion \
disagreement itself): {svm_agrees_with_prediction}

Decide HUMAN_REVIEW, not ACCEPT, when any of these hold:
- foreign_municipality is not "none" -- the document may not even be from \
Municipalidad de Rosario, which no amount of label-matching fixes.
- the document text does not clearly match the anchor for {primary_label} above.
- second_opinion_label disagrees with the primary label AND you cannot tell from \
the text which of the two is actually correct.
Otherwise, a high risk_score or a non-empty smells list is a reason for caution -- \
mention it in your reasoning -- but not by itself a reason to override a label the \
text clearly supports.

When the primary and second-opinion labels disagree, decide which one the document \
text actually supports using the category anchors above, and return that exact label \
string as final_label -- never a different category, even if you believe neither \
candidate is fully correct. Trust the second opinion's disagreement more when its \
statistical grounding above is in-distribution/calibrated/SVM-consistent, and less \
when it is out-of-distribution, uncalibrated, or SVM-inconsistent -- that grounding \
describes how reliable the second opinion's OWN prediction is, separate from whether \
it agrees with the primary label. If the text is genuinely ambiguous between the two, \
still pick the more likely candidate and reflect the uncertainty in reasoning, not by \
refusing to choose. If second_opinion_label is "none" or matches the primary label, \
final_label is simply {primary_label}.

Document text: {cleaned_text}

Answer with a single JSON object and nothing else.

JSON:
{{"accept": "true or false -- true means the primary label is correct and safe to accept", \
"final_label": "the label the evidence actually supports -- must be exactly {primary_label} \
or {second_opinion_label}, never a third category", \
"reasoning": "one short sentence citing the specific evidence -- textual or signal-based -- \
behind your decision"}}"""
```

Add a helper function building `ood_signal_block`, and update `_format_prompt`:
```python
def _ood_signal_block(ood_metrics: OodMetrics | None) -> str:
    if ood_metrics is None:
        return "not available (second opinion disabled or OOD scoring not configured)"
    mahalanobis_note = (
        "-- degenerate calibration, this specific model's calibration step could not "
        "produce a reliable p-value here; do not treat this value as trustworthy evidence"
        if ood_metrics.mahalanobis_calibration_status == "refused_degenerate"
        else f"-- {ood_metrics.mahalanobis_calibration_status}"
    )
    return (
        f"- mahalanobis_p_value: {ood_metrics.mahalanobis_p_value} "
        f"(low = anomalous/atypical for the predicted class, high = statistically "
        f"typical) {mahalanobis_note}\n"
        f"- cosine_z: {ood_metrics.cosine_z} (near 0 = typical, large magnitude = "
        f"anomalous) -- {ood_metrics.cosine_calibration_status}\n"
        f"- knn_distance: {ood_metrics.knn_distance} (distance to nearest training "
        f"examples of the predicted class in embedding space; larger = less similar "
        f"to anything this model was trained on) "
        f"-- {ood_metrics.knn_distance_calibration_status}\n"
        f"- in_distribution: {ood_metrics.in_distribution} (headline summary: whether "
        f"any calibrated signal above actually fired as anomalous)"
    )


def _format_prompt(chain_input: JudgeInput) -> str:
    return _TEMPLATE.format(
        category_anchors=_CATEGORY_ANCHORS_BLOCK,
        cleaned_text=chain_input.cleaned_text,
        primary_label=chain_input.primary_label,
        primary_confidence=chain_input.primary_confidence,
        second_opinion_label=chain_input.second_opinion_label or "none",
        second_opinion_confidence=(
            "n/a"
            if chain_input.second_opinion_confidence is None
            else chain_input.second_opinion_confidence
        ),
        smells=", ".join(chain_input.smells) or "none",
        risk_score=chain_input.risk_score,
        foreign_municipality=chain_input.foreign_municipality or "none",
        ood_signal_block=_ood_signal_block(chain_input.ood_metrics),
        svm_agrees_with_prediction=chain_input.svm_agrees_with_prediction,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/classification/test_llm_judge_chain.py -v`
Expected: all PASS, including the two new tests from Step 1.

- [ ] **Step 6: Run the broader classification test suite to check for regressions**

Run: `uv run pytest tests/classification/ -v`
Expected: all PASS (no other test constructs `JudgeInput` with positional args that
would break from the new fields — all existing tests use keyword construction with
defaults, per the `_input()` helper's `model_validate(defaults)` pattern already
shown in `test_llm_judge_chain.py`).

- [ ] **Step 7: Commit**

```bash
git add src/classiflow/classification/prompts/llm_judge.py tests/classification/test_llm_judge_chain.py
git commit -m "feat: LLM judge prompt interprets OOD/SVM statistical signals, not just smells/risk_score"
```

---

## Task 5: Coordinator wires the new signals through; disagreement path always stays HUMAN_REVIEW

**Files:**
- Modify: `src/classiflow/classification/coordinator.py:103-117`
- Test: `tests/classification/test_coordinator.py`

**Interfaces:**
- Consumes: `state.get("second_opinion_confidence")`, `state.get("ood_metrics")`,
  `state.get("svm_agrees_with_prediction", True)`, `state.get("classifier_disagreement",
  False)` — all already-present `ClassificationState` keys (set by `_second_opinion`'s
  closure, `coordinator.py:52-66`); no `ClassificationState`/`ClassificationUpdate`
  schema change needed.
- Produces: `_llm_judge` closure's `review_route` is now `HUMAN_REVIEW` whenever
  `classifier_disagreement` was `True` when the judge ran, regardless of
  `JudgeOutput.accept` — this is the critical, non-negotiable invariant restated in
  Global Constraints above.

- [ ] **Step 1: Write the failing test for the disagreement-to-judge-to-human-review path**

Add to `tests/classification/test_coordinator.py`, a mock second-opinion classifier
that disagrees with the primary label, and a new test class:
```python
class _DisagreeingClassifier:
    def predict(self, _text: str) -> SecondOpinionResult:
        return SecondOpinionResult(
            label="resolucion_concejo_municipal",
            confidence=0.996,
            svm_agrees_with_prediction=False,
        )


def _build_graph_with_disagreement(
    tmp_path: Path, *, judge_response: str
) -> tuple[object, InMemoryClassificationRecordRepository]:
    audit = AuditService(InMemoryAuditRepository())
    broadcaster = EventBroadcaster()
    config = ClassificationConfig(second_opinion_enabled=True, foreign_municipality_enabled=True)
    repo = InMemoryClassificationRecordRepository()
    storage = LocalDiskStorage(root=str(tmp_path))

    primary = PrimaryClassifierNode(
        audit=audit,
        broadcaster=broadcaster,
        classification_chain=build_classification_chain(
            MockLlm(response=_HIGH_CONFIDENCE_RESPONSE)
        ),
        config=config,
    )
    second_opinion = SecondOpinionNode(
        audit=audit, broadcaster=broadcaster, classifier=_DisagreeingClassifier(), config=config
    )
    foreign_municipality = ForeignMunicipalityNode(
        audit=audit, broadcaster=broadcaster, config=config
    )
    smells_risk = SmellsRiskNode(audit=audit, broadcaster=broadcaster, config=config)
    confidence_gate = ConfidenceGateNode(audit=audit, broadcaster=broadcaster, config=config)
    llm_judge = LlmJudgeNode(
        audit=audit,
        broadcaster=broadcaster,
        judge_chain=build_judge_chain(MockLlm(response=judge_response)),
    )
    routing = RoutingNode(
        audit=audit, broadcaster=broadcaster, storage=storage, classification_repo=repo
    )
    graph = build_classification_coordinator(
        primary,
        second_opinion,
        foreign_municipality,
        smells_risk,
        confidence_gate,
        llm_judge,
        routing,
    )
    return graph, repo


class TestClassificationCoordinatorDisagreementPath:
    async def test_disagreement_reaches_judge_and_stays_human_review_even_when_judge_accepts(
        self, tmp_path: Path
    ) -> None:
        # Critical invariant: JudgeOutput.accept=True must NOT flip a disagreement
        # case to ACCEPT -- disagreement always stays HUMAN_REVIEW regardless of the
        # judge's verdict, per the spec's non-negotiable constraint.
        judge_accepts_response = (
            '{"accept": true, "final_label": "resoluciones_concejo_municipal", '
            '"reasoning": "second opinion is correct"}'
        )
        graph, repo = _build_graph_with_disagreement(
            tmp_path, judge_response=judge_accepts_response
        )
        job_id = "coord-disagreement-001"
        filename = "resolucion_cm.pdf"
        _stage_file(tmp_path, job_id, filename)
        initial: ClassificationState = {
            "job_id": job_id,
            "filename": filename,
            "cleaned_text": "Artículo 1º — texto de una resolución del Concejo Municipal.",
            "enriched_id": 1,
        }
        result = await graph.ainvoke(initial)

        assert result["classifier_disagreement"] is True
        assert result["judged_by_llm"] is True
        assert result["review_route"] == "human_review"

        record = await repo.find_by_job_id(job_id)
        assert record is not None
        assert record.review_route == "human_review"
        assert record.classifier_disagreement is True

    async def test_judge_input_receives_ood_and_svm_signals(self, tmp_path: Path) -> None:
        captured: dict[str, JudgeInput] = {}

        class _CapturingJudgeChain:
            def invoke(self, inp: JudgeInput, **_kwargs: object) -> JudgeOutput:
                captured["input"] = inp
                return JudgeOutput(accept=False, final_label=inp.primary_label, reasoning="test")

        audit = AuditService(InMemoryAuditRepository())
        broadcaster = EventBroadcaster()
        config = ClassificationConfig(
            second_opinion_enabled=True, foreign_municipality_enabled=True
        )
        repo = InMemoryClassificationRecordRepository()
        storage = LocalDiskStorage(root=str(tmp_path))
        graph = build_classification_coordinator(
            PrimaryClassifierNode(
                audit=audit,
                broadcaster=broadcaster,
                classification_chain=build_classification_chain(
                    MockLlm(response=_HIGH_CONFIDENCE_RESPONSE)
                ),
                config=config,
            ),
            SecondOpinionNode(
                audit=audit,
                broadcaster=broadcaster,
                classifier=_DisagreeingClassifier(),
                config=config,
            ),
            ForeignMunicipalityNode(audit=audit, broadcaster=broadcaster, config=config),
            SmellsRiskNode(audit=audit, broadcaster=broadcaster, config=config),
            ConfidenceGateNode(audit=audit, broadcaster=broadcaster, config=config),
            LlmJudgeNode(audit=audit, broadcaster=broadcaster, judge_chain=_CapturingJudgeChain()),
            RoutingNode(
                audit=audit, broadcaster=broadcaster, storage=storage, classification_repo=repo
            ),
        )
        job_id = "coord-disagreement-002"
        filename = "resolucion_cm.pdf"
        _stage_file(tmp_path, job_id, filename)
        initial: ClassificationState = {
            "job_id": job_id,
            "filename": filename,
            "cleaned_text": "Artículo 1º — texto de una resolución del Concejo Municipal.",
            "enriched_id": 1,
        }
        await graph.ainvoke(initial)

        judge_input = captured["input"]
        assert judge_input.second_opinion_confidence == 0.996
        assert judge_input.svm_agrees_with_prediction is False
```
Add the needed imports at the top of `tests/classification/test_coordinator.py`:
`JudgeInput` from `classiflow.classification.prompts.llm_judge`, `JudgeOutput` from
`classiflow.classification.domain.results`.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/classification/test_coordinator.py -v`
Expected: `test_disagreement_reaches_judge_and_stays_human_review_even_when_judge_accepts`
FAILs — today's `_llm_judge` closure derives `review_route` purely from
`result.accept` (`ReviewRoute.ACCEPT if result.accept else ReviewRoute.HUMAN_REVIEW`),
so `accept=True` currently yields `ACCEPT`, not `HUMAN_REVIEW`.
`test_judge_input_receives_ood_and_svm_signals` also FAILs — `JudgeInput` is
constructed today without `second_opinion_confidence`/`svm_agrees_with_prediction`.

- [ ] **Step 3: Update the `_llm_judge` closure in `coordinator.py`**

Replace:
```python
    async def _llm_judge(state: ClassificationState) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        judge_input = JudgeInput(
            cleaned_text=state["cleaned_text"],
            primary_label=state["label"],
            primary_confidence=state["confidence"],
            second_opinion_label=state.get("second_opinion_label"),
            smells=state.get("smells", []),
            risk_score=state.get("risk_score", 0),
            foreign_municipality=state.get("foreign_municipality"),
        )
        result = await llm_judge.run(ctx, judge_input)
        review_route = ReviewRoute.ACCEPT if result.accept else ReviewRoute.HUMAN_REVIEW
        return _dump(ClassificationUpdate(review_route=review_route, judged_by_llm=True))
```
with:
```python
    async def _llm_judge(state: ClassificationState) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        judge_input = JudgeInput(
            cleaned_text=state["cleaned_text"],
            primary_label=state["label"],
            primary_confidence=state["confidence"],
            second_opinion_label=state.get("second_opinion_label"),
            second_opinion_confidence=state.get("second_opinion_confidence"),
            ood_metrics=state.get("ood_metrics"),
            svm_agrees_with_prediction=state.get("svm_agrees_with_prediction", True),
            smells=state.get("smells", []),
            risk_score=state.get("risk_score", 0),
            foreign_municipality=state.get("foreign_municipality"),
        )
        result = await llm_judge.run(ctx, judge_input)
        # Disagreement is judged strictly higher-risk than low-confidence-alone: the
        # judge's verdict is captured as advisory data below (Task 6 persists
        # final_label/reasoning), but a disagreement case NEVER auto-accepts, no
        # matter what the judge concludes. Only the low-confidence-no-disagreement
        # path still derives the route from JudgeOutput.accept, unchanged from today.
        if state.get("classifier_disagreement", False):
            review_route = ReviewRoute.HUMAN_REVIEW
        else:
            review_route = ReviewRoute.ACCEPT if result.accept else ReviewRoute.HUMAN_REVIEW
        return _dump(ClassificationUpdate(review_route=review_route, judged_by_llm=True))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/classification/test_coordinator.py -v`
Expected: all PASS, including both new tests and the pre-existing
`test_low_confidence_routes_through_judge_to_accept` (still passes — that path has
`classifier_disagreement` absent/`False`, so it still derives the route from
`result.accept` exactly as before).

- [ ] **Step 5: Run the full classification test suite**

Run: `uv run pytest tests/classification/ tests/shared/ -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/classiflow/classification/coordinator.py tests/classification/test_coordinator.py
git commit -m "feat: coordinator passes OOD/SVM signals to the judge; disagreement always stays human_review"
```

---

## Task 6: Persist `judge_final_label`/`judge_reasoning`; expose them in the review-queue API

**Files:**
- Modify: `src/classiflow/database/models.py:126-158` (`ClassificationRecord`)
- Modify: `src/classiflow/classification/domain/results.py:18-37` (`RoutingInput`)
- Modify: `src/classiflow/classification/domain/state.py` (`ClassificationState`,
  `ClassificationUpdate`)
- Modify: `src/classiflow/classification/nodes/routing.py:59-96` (`_save_record`)
- Modify: `src/classiflow/classification/coordinator.py` (`_llm_judge`, `_routing`
  closures)
- Modify: `src/classiflow/api/routes/classification/schemas.py` (`ReviewQueueItem`)
- Create: `alembic/versions/0006_add_judge_verdict_fields.py`
- Test: `tests/classification/test_routing_node.py`, `tests/classification/test_coordinator.py`

**Interfaces:**
- Consumes: `JudgeOutput.final_label`/`JudgeOutput.reasoning` (Task 3).
- Produces: `ClassificationRecord.judge_final_label: str | None`,
  `ClassificationRecord.judge_reasoning: str | None`; `RoutingInput.judge_final_label:
  str | None = None`, `RoutingInput.judge_reasoning: str | None = None`;
  `ReviewQueueItem.judge_final_label`/`judge_reasoning`/`second_opinion_label` (the
  human reviewer's three-opinion view named in the spec).

- [ ] **Step 1: Write the failing test for `RoutingNode` persisting the new fields**

Add to `tests/classification/test_routing_node.py`:
```python
    async def test_persists_judge_verdict_fields(self) -> None:
        repo = InMemoryClassificationRecordRepository()
        node = RoutingNode(
            audit=AuditService(InMemoryAuditRepository()),
            broadcaster=EventBroadcaster(),
            storage=_FakeStorage(),
            classification_repo=repo,
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        await node.run(
            ctx,
            _routing_input(
                review_route="human_review",
                judged_by_llm=True,
                judge_final_label="resoluciones_concejo_municipal",
                judge_reasoning="second opinion's evidence is stronger here",
            ),
        )
        record = await repo.find_by_job_id(_JOB_ID)
        assert record is not None
        assert record.judge_final_label == "resoluciones_concejo_municipal"
        assert record.judge_reasoning == "second opinion's evidence is stronger here"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/classification/test_routing_node.py -v`
Expected: FAIL — `RoutingInput` has no `judge_final_label`/`judge_reasoning` fields
(`model_validate` with unknown-but-ignored extra kwargs means construction succeeds,
but `record.judge_final_label` raises `AttributeError` since `ClassificationRecord`
has no such column yet either).

- [ ] **Step 3: Add the migration**

Create `alembic/versions/0006_add_judge_verdict_fields.py`:
```python
"""Add judge_final_label/judge_reasoning to classification_records

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-22

"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "classification_records", sa.Column("judge_final_label", sa.String(100), nullable=True)
    )
    op.add_column("classification_records", sa.Column("judge_reasoning", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("classification_records", "judge_reasoning")
    op.drop_column("classification_records", "judge_final_label")
```

- [ ] **Step 4: Add the columns to `ClassificationRecord`**

In `src/classiflow/database/models.py`, add after the `judged_by_llm` line:
```python
    # Whether the LLM Judge tier ran and produced the final review_route (spec Decision 6).
    judged_by_llm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Populated only when judged_by_llm=True (spec Decision 2's judge-as-advisory-opinion).
    judge_final_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    judge_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 5: Add the fields to `RoutingInput`**

In `src/classiflow/classification/domain/results.py`, add to `RoutingInput`:
```python
    judged_by_llm: bool = False
    judge_final_label: str | None = None
    judge_reasoning: str | None = None
    human_overridden: bool = False
```
(inserting the two new fields right after the existing `judged_by_llm: bool = False`
line, before `human_overridden`).

- [ ] **Step 6: Update `RoutingNode._save_record` to persist the new fields**

In `src/classiflow/classification/nodes/routing.py`, add after
`record.judged_by_llm = routing_input.judged_by_llm`:
```python
        record.judged_by_llm = routing_input.judged_by_llm
        record.judge_final_label = routing_input.judge_final_label
        record.judge_reasoning = routing_input.judge_reasoning
```

- [ ] **Step 7: Wire the coordinator's `_routing` closure to pass the new fields through**

`_llm_judge`'s closure result already returns `judged_by_llm=True` via
`ClassificationUpdate` — it needs to also carry `judge_final_label`/`judge_reasoning`
into state so `_routing` can read them.

In `src/classiflow/classification/domain/state.py`, add the two new keys to
`ClassificationState` (after `judged_by_llm: bool`, before `stored_path: str`):
```python
    review_route: str
    judged_by_llm: bool
    judge_final_label: str
    judge_reasoning: str
    stored_path: str
```
And to `ClassificationUpdate` (after `judged_by_llm: bool | None = None`, before
`stored_path: str | None = None`), following the same `None`-means-unset pattern
every other field in this class already documents in its own docstring:
```python
    review_route: str | None = None
    judged_by_llm: bool | None = None
    judge_final_label: str | None = None
    judge_reasoning: str | None = None
    stored_path: str | None = None
```

In `coordinator.py`'s `_llm_judge` closure, extend the final return:
```python
        return _dump(
            ClassificationUpdate(
                review_route=review_route,
                judged_by_llm=True,
                judge_final_label=result.final_label,
                judge_reasoning=result.reasoning,
            )
        )
```
In `_routing`'s `RoutingInput(...)` construction, add `judge_final_label` and
`judge_reasoning` right after the existing `judged_by_llm=...` line:
```python
        routing_input = RoutingInput(
            job_id=state["job_id"],
            filename=state["filename"],
            enriched_id=state["enriched_id"],
            label=state["label"],
            confidence=state["confidence"],
            all_scores=state.get("all_scores", {}),
            second_opinion_label=state.get("second_opinion_label"),
            second_opinion_confidence=state.get("second_opinion_confidence", 0.0),
            classifier_disagreement=state.get("classifier_disagreement", False),
            ood_metrics=state.get("ood_metrics"),
            svm_scores=state.get("svm_scores", {}),
            svm_agrees_with_prediction=state.get("svm_agrees_with_prediction", True),
            review_route=state["review_route"],
            smells=state.get("smells", []),
            risk_score=state.get("risk_score", 0),
            smell_review_suggested=state.get("smell_review_suggested", False),
            foreign_municipality=state.get("foreign_municipality"),
            judged_by_llm=state.get("judged_by_llm", False),
            judge_final_label=state.get("judge_final_label"),
            judge_reasoning=state.get("judge_reasoning"),
        )
```
(only the last two lines, `judge_final_label=...` and `judge_reasoning=...`, are new
— every other line already exists in `_routing` unchanged.)

- [ ] **Step 8: Add `judge_final_label`/`judge_reasoning`/`second_opinion_label` to the review-queue API schema**

In `src/classiflow/api/routes/classification/schemas.py`, replace:
```python
class ReviewQueueItem(BaseSchema):
    job_id: str
    label: str | None
    confidence: float
    review_route: str
    smells: list[str]
    risk_score: int
    smell_review_suggested: bool
    foreign_municipality: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, record: ClassificationRecord) -> "ReviewQueueItem":
        return cls(
            job_id=record.job_id,
            label=record.label,
            confidence=record.confidence,
            review_route=record.review_route,
            smells=record.smells,
            risk_score=record.risk_score,
            smell_review_suggested=record.smell_review_suggested,
            foreign_municipality=record.foreign_municipality,
            created_at=record.created_at,
        )
```
with:
```python
class ReviewQueueItem(BaseSchema):
    job_id: str
    label: str | None
    confidence: float
    second_opinion_label: str | None
    review_route: str
    smells: list[str]
    risk_score: int
    smell_review_suggested: bool
    foreign_municipality: str | None
    judged_by_llm: bool
    judge_final_label: str | None
    judge_reasoning: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, record: ClassificationRecord) -> "ReviewQueueItem":
        return cls(
            job_id=record.job_id,
            label=record.label,
            confidence=record.confidence,
            second_opinion_label=record.second_opinion_label,
            review_route=record.review_route,
            smells=record.smells,
            risk_score=record.risk_score,
            smell_review_suggested=record.smell_review_suggested,
            foreign_municipality=record.foreign_municipality,
            judged_by_llm=record.judged_by_llm,
            judge_final_label=record.judge_final_label,
            judge_reasoning=record.judge_reasoning,
            created_at=record.created_at,
        )
```

- [ ] **Step 9: Run tests to verify Step 1's test now passes**

Run: `uv run pytest tests/classification/test_routing_node.py tests/classification/test_coordinator.py -v`
Expected: all PASS.

- [ ] **Step 10: Check for an existing `ReviewQueueItem`/`from_model` test and extend or add one**

Search: `uv run pytest tests/api/routes/test_classification.py -v --collect-only` to
see if a `from_model`/review-queue serialization test already exists. If one exists,
extend its assertions to cover the three new fields. If none exists, add a minimal
one in `tests/api/routes/test_classification.py` following that file's existing
`ClassificationRecord` construction pattern, asserting `ReviewQueueItem.from_model(record)`
round-trips `judge_final_label`/`judge_reasoning`/`second_opinion_label` correctly.

- [ ] **Step 11: Run the full test suite and `uv run poe check`**

Hand these two commands to the user (per this project's execution-workflow rule) or
run them yourself if you have direct execution permission for non-notebook commands:
```
uv run pytest tests/ -v
uv run poe check
```
Expected: all PASS.

- [ ] **Step 12: Commit**

```bash
git add src/classiflow/database/models.py src/classiflow/classification/domain/results.py src/classiflow/classification/domain/state.py src/classiflow/classification/nodes/routing.py src/classiflow/classification/coordinator.py src/classiflow/api/routes/classification/schemas.py alembic/versions/0006_add_judge_verdict_fields.py tests/classification/test_routing_node.py tests/classification/test_coordinator.py
git commit -m "feat: persist and expose the LLM judge's final_label/reasoning verdict on the review queue"
```

---

## Task 7: Concejo-municipal sibling-pair prompt tuning (Decision 3)

**Files:**
- Modify: `src/classiflow/classification/prompts/primary_classification.py`
  (`_TEMPLATE` and/or `_CATEGORY_DEFS`)
- Test: `tests/classification/test_primary_classification_chain.py` (existing file —
  add a case only if the trace below produces a rule expressible as a `MockLlm`-based
  unit test; the primary validation for this task is direct real-model tracing, per
  the spec, not new automated tests)

**Interfaces:**
- Consumes: `data/classiflow.db`'s `EnrichedRecord.cleaned_text` for the two traced
  documents (`resolucion_cm_16879_2024.pdf`, `resolucion_cm_197_2024.pdf`).
- Produces: one targeted edit to `_TEMPLATE`'s `Rules:` block or `_CATEGORY_DEFS`,
  validated against both failing rows and the regression-check row set below.

- [ ] **Step 1: Pull the real `cleaned_text` for both failing documents**

Run a one-off script (not committed — this is diagnostic, use the scratchpad
directory) that does:
```python
import asyncio
from sqlalchemy import select
from classiflow.database.session import (
    get_session,
)  # confirm exact import path first via codegraph_explore("get_session AsyncSession database engine")
from classiflow.database.models import EnrichedRecord, Job


async def main() -> None:
    async with get_session() as session:
        for filename in ("resolucion_cm_16879_2024.pdf", "resolucion_cm_197_2024.pdf"):
            job = (
                await session.execute(select(Job).where(Job.filename == filename))
            ).scalar_one_or_none()
            if job is None:
                print(f"{filename}: no Job row found")
                continue
            record = (
                await session.execute(
                    select(EnrichedRecord).where(EnrichedRecord.job_id == job.job_id)
                )
            ).scalar_one_or_none()
            print(f"=== {filename} ===")
            print(record.cleaned_text if record else "no EnrichedRecord found")


asyncio.run(main())
```
Confirm the exact session-acquisition helper name via
`codegraph_explore("AsyncSession session database engine get_session")` before
writing this script — do not guess the import path.

- [ ] **Step 2: Invoke the primary classification chain directly at temperature=0 against both texts**

```python
from classiflow.classification.prompts.primary_classification import build_classification_chain, PrimaryClassificationInput
from classiflow.ingesta.llm_provider import get_llm_langchain
from classiflow.settings import Settings

llm = get_llm_langchain(Settings.classification_model_path)  # temperature comes from Settings.SLM_TEMPERATURE; for this diagnostic only, construct a second LlamaCpp instance with temperature=0.0 by calling ChatTemplatedLlamaCpp directly rather than mutating Settings, to avoid touching production sampling config
chain = build_classification_chain(llm)
for text in (text_16879, text_197):  # from Step 1
    output = chain.invoke(PrimaryClassificationInput(cleaned_text=text[:Settings... ]))  # match config.max_input_tokens truncation
    print(output.label, output.confidence, output.model_dump())
```
Read the raw `reasoning` field verbatim for both. This tells you which specific
textual signal the model weighted incorrectly — e.g. does it see "Concejo Municipal"
in the header but still default to `decretos`? Does it correctly identify the
issuing body but miss the `RESOLUCION` vs `DECRETO` noun distinction from
`_CATEGORY_ANCHORS`'s documented "HA SANCIONADO LA SIGUIENTE: X" formula?

- [ ] **Step 3: Based on the trace, make ONE targeted edit to `_TEMPLATE` or `_CATEGORY_DEFS`**

The exact wording is intentionally not prescribed here — the spec is explicit that
this is contingent on what Step 2's trace reveals (mirroring how the earlier
Concejo-override rule and `compendios_de_boletines` tightening were each developed:
trace first, write one precise rule, validate). Whatever the edit turns out to be,
it must be a single additive rule or definition tightening — not a rewrite of
`_TEMPLATE`'s existing structure.

- [ ] **Step 4: Validate against both failing rows using the same direct-invocation harness**

Re-run Step 2's script against the edited prompt. Expected: both
`resolucion_cm_16879_2024.pdf` and `resolucion_cm_197_2024.pdf` now classify as
`resoluciones_concejo_municipal`, or at minimum no longer silently agree with a wrong
label (i.e. if still wrong, `classifier_disagreement` at least fires so Task 5's
judge path catches it).

- [ ] **Step 5: Validate no regression on the previously-passing rows**

Using the same harness, re-run against: `decreto_cm_10554_1995.pdf`,
`decreto_cm_1016_2025.pdf`, `decreto_1000_2008.pdf`, `resolucion_100_2020.pdf`.
Expected: all four still classify correctly after the edit.

- [ ] **Step 6: If the trace produces a rule expressible as a deterministic `MockLlm` test, add it**

Only if Step 3's edit is a structural prompt change verifiable independent of real
model behavior (e.g. a new category anchor string that should appear in
`_format_prompt`'s output) — add a case to
`tests/classification/test_primary_classification_chain.py` following its existing
pattern. If the fix is purely about how the real model interprets nuanced text
(the expected case, per the spec), skip this step — the validation is Steps 4-5, not
a new automated test.

- [ ] **Step 7: Commit**

```bash
git add src/classiflow/classification/prompts/primary_classification.py
git commit -m "fix: tighten primary classifier prompt for the Concejo-municipal sibling-pair confusion"
```
(Include the test file in the `git add` list only if Step 6 produced one.)

---

## Task 8: OCR/extraction quality investigation (Decision 4)

**Files:** none modified unless the investigation produces a low-risk, approved fix
(see Step 5 below) — this task's primary deliverable is a written finding, not code.

**Interfaces:**
- Consumes: `Settings.OCR_LANG`, `Settings.OCR_RENDER_DPI`
  (`src/classiflow/settings.py:45-46`), `extractors/ocr.py`'s OCR pipeline,
  `ExtractionResult.extractor_used`.
- Produces: a written finding (present it to the user in chat, not a new doc file per
  ponytail/YAGNI — no unrequested markdown report).

- [ ] **Step 1: Confirm which extraction path each of the three worst-OCR documents actually took**

Query `data/classiflow.db` for `declaracion_2501_1991.pdf`,
`decreto_ordenanza_1182_1976.pdf`, `decreto_ordenanza_1314_1980.pdf`'s
`ExtractionResult.extractor_used` (via each `Job`'s associated `DocumentStep` detail
for the extraction node, or by re-running extraction directly against the original
file and checking the return value) — confirm they went through OCR, not MarkItDown.

- [ ] **Step 2: Re-run OCR extraction directly at higher DPI for side-by-side comparison**

Using `extractors/ocr.py`'s extraction function directly (bypassing the pipeline),
render each of the three documents at DPI 200 (current), 300, and 400, and compare
output legibility — specifically, does article/number/date text that's currently
garbled become readable at a higher DPI?

- [ ] **Step 3: Check whether `OCR_LANG="es"` is the right hint for `decreto_ordenanza_1314_1980.pdf`**

This document was previously misdetected as Esperanto at the Lingua language-detection
stage (`node3_content_validation.py`), not at OCR itself. Determine: does the OCR
output at any tested DPI actually look like garbled/non-Spanish text (suggesting OCR
quality is the root cause feeding a bad signal into language detection), or does OCR
produce recognizable Spanish text that Lingua still misclassifies (suggesting the
language detector itself is the weak link, independent of OCR)?

- [ ] **Step 4: Report findings to the user in chat**

State plainly: does DPI materially improve legibility for these documents; is
`OCR_LANG` a contributing factor or a red herring; is there a concrete, low-risk
recommendation (e.g. "raise `OCR_RENDER_DPI` to 300, no other changes"), or does this
corpus's scan quality need a different tool/approach entirely (name that conclusion
if it's what the evidence shows, without proposing to build it here).

- [ ] **Step 5: Only if Step 4 finds a clear, low-risk win — apply it as its own small change**

E.g. if raising `OCR_RENDER_DPI`'s default from 200 to 300 is the finding, that's a
one-line change to `src/classiflow/settings.py:46`. Re-run the three documents
through the real pipeline (hand the notebook-execution command to the user, per the
execution-workflow rule) to confirm no regression before committing. If the finding
is inconclusive or the fix is invasive (e.g. swapping OCR engines), stop here and
report that conclusion instead — do not force a code change this task didn't
actually earn.

- [ ] **Step 6: Commit (only if Step 5 produced a change)**

```bash
git add src/classiflow/settings.py
git commit -m "fix: raise OCR render DPI default based on legibility comparison on scanned documents"
```

---

## Task 9: Persist raw Stage 2 extraction text on `EnrichedRecord` (Decision 5)

**Files:**
- Modify: `src/classiflow/database/models.py:108-123` (`EnrichedRecord`)
- Modify: `src/classiflow/services/pipeline/service.py:157-188` (`_run_enrichment`)
- Create: `alembic/versions/0007_add_enriched_record_raw_text.py`
- Test: `tests/shared/test_pipeline_service_enrichment.py`

**Interfaces:**
- Consumes: `final_state["text"]` — already in scope inside `_run_enrichment`
  (`service.py:166`, passed into `EnrichmentState["text"]`); this is Stage 2's raw,
  pre-cleaning extraction output.
- Produces: `EnrichedRecord.raw_text: str | None` — queryable via
  `select(EnrichedRecord.raw_text).where(...)` for future embedding work (out of
  scope here per the spec's non-goals).

- [ ] **Step 1: Write the failing test**

Add an assertion to the existing happy-path test in
`tests/shared/test_pipeline_service_enrichment.py`:
```python
class TestPipelineServiceEnrichmentHappyPath:
    async def test_accepted_job_gets_enriched_record(self, tmp_path: Path) -> None:
        under_test = _build_service(_VALID_ENTITY_RESPONSE, tmp_path)
        background_tasks = BackgroundTasks()
        job_id = await under_test.service.start(background_tasks, "ordenanza.pdf", _MINIMAL_PDF)
        for task in background_tasks.tasks:
            await task()

        job = await under_test.job_repo.find_by_job_id(job_id)
        assert job is not None
        assert job.status == "accepted"

        record = await under_test.enriched_record_repo.find_by_job_id(job_id)
        assert record is not None
        assert "Artículo 1" in record.cleaned_text
        assert record.raw_text == _SPANISH_TEXT
        assert record.entities["doc_type_hint"] == "ordenanza"
        assert record.metadata_["source"] == "manual_upload"
```
(`_SPANISH_TEXT` is the module-level fixture already used as the `ExtractionStep`'s
stubbed extraction output in this test file — Stage 2's "raw" text in this test setup
IS `_SPANISH_TEXT` verbatim, since the stub extractor returns it unchanged and no
Stage-2-level cleaning happens before enrichment.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/shared/test_pipeline_service_enrichment.py -v`
Expected: FAIL — `EnrichedRecord` has no `raw_text` attribute yet.

- [ ] **Step 3: Add the migration**

Create `alembic/versions/0007_add_enriched_record_raw_text.py`:
```python
"""Add raw_text to enriched_records

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-22

"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("enriched_records", sa.Column("raw_text", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("enriched_records", "raw_text")
```
(Depends on Task 6's `0006` migration landing first — if Task 6 is skipped or
reordered, update `down_revision` to whatever the actual prior head revision is at
execution time, per the spec's own open question about exact revision numbers.)

- [ ] **Step 4: Add the column to `EnrichedRecord`**

In `src/classiflow/database/models.py`, replace:
```python
class EnrichedRecord(Base):
    __tablename__ = "enriched_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True
    )
    cleaned_text: Mapped[str] = mapped_column(Text, nullable=False)
    entities: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
```
with:
```python
class EnrichedRecord(Base):
    __tablename__ = "enriched_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True
    )
    cleaned_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Stage 2's raw, pre-cleaning extraction output -- nullable because a migration
    # cannot backfill historical rows. Populated for every accepted job (unlike
    # Job.extracted_text, which only persists for non-accepted jobs) so it is
    # available for future embedding/analysis work.
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    entities: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
```

- [ ] **Step 5: Populate `raw_text` in `_run_enrichment`**

In `src/classiflow/services/pipeline/service.py`, replace:
```python
                record = EnrichedRecord(
                    job_id=job_id,
                    cleaned_text=result["cleaned_text"],
                    entities=result["entities"].model_dump(),
                    metadata_=result["metadata"].model_dump(),
                )
```
with:
```python
                record = EnrichedRecord(
                    job_id=job_id,
                    cleaned_text=result["cleaned_text"],
                    raw_text=final_state["text"],
                    entities=result["entities"].model_dump(),
                    metadata_=result["metadata"].model_dump(),
                )
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/shared/test_pipeline_service_enrichment.py -v`
Expected: all PASS.

- [ ] **Step 7: Run the full test suite and `uv run poe check`**

Hand these to the user or run directly if permitted:
```
uv run pytest tests/ -v
uv run poe check
```
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/classiflow/database/models.py src/classiflow/services/pipeline/service.py alembic/versions/0007_add_enriched_record_raw_text.py tests/shared/test_pipeline_service_enrichment.py
git commit -m "feat: persist raw pre-cleaning extraction text on EnrichedRecord for future embedding use"
```

---

## Final verification

- [ ] Run `uv run poe check` (lint + typecheck) — hand to the user per this project's
  execution-workflow rule, or run directly if you have that permission in this
  session.
- [ ] Run `uv run pytest tests/ -v` — all tests pass, including every new/updated
  test across Tasks 2-6 and 9.
- [ ] Run `uv run --all-groups pre-commit run --all-files` before requesting PR
  authorization, per this project's PR authorization protocol in `CLAUDE.md`.
- [ ] Hand over `uv run jupyter execute src/classiflow/playground/stage4/full_pipeline_end_to_end.ipynb`
  for the user to confirm Task 1's report fix and spot-check Task 7's prompt tuning
  against the real corpus.
- [ ] Present the change summary (each file touched, what changed, test results) and
  ask "Do you authorize the PR creation?" before running any `git commit`/`git push`/
  `gh pr create` beyond the per-task commits already made during implementation —
  per `CLAUDE.md`'s PR authorization protocol, task-level commits during development
  are expected, but opening a PR against the branch still needs explicit
  authorization.

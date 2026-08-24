# Adding `otro` as a Real Document Category — Design

## Context

`DocumentCategory` (`classification/domain/categories.py`) defines 10 municipal
document types. The primary LLM classifier's prompt (`primary_classification.py`)
forces exactly one of these 10 onto every document, with no escape hatch — even a
document that isn't from Municipalidad de Rosario at all gets force-labeled into one
of the 10 real categories.

This was directly observed this session: `A0470.pdf`, a Banco Central de la República
Argentina circular (not a municipal document at all — wrong issuer entirely, nothing
to do with Municipalidad de Rosario), was labeled `resoluciones` by the primary
classifier at 0.900 confidence. BETO v2 (the Second Opinion Agent) — which was
already trained with its own `otro` catch-all class, unused until now — correctly
predicted `otro` at 0.995 confidence. But `classifier_disagreement()`
(`bert/label_mapping.py`) has a guard clause that returns `False` whenever BETO's own
label is `otro`, on the reasoning that "no Classiflow equivalent exists to compare
against." That guard meant this case never reached the LLM Judge or human review — it
silently auto-accepted a confidently wrong label, exactly the failure mode the
Judge-as-arbiter work (this session, spec
`2026-08-22-classification-accuracy-improvements-design.md`) was built to catch, but
couldn't here because the comparison itself was skipped.

BETO already computing a real, calibrated `otro` prediction — and the pipeline
throwing that signal away — is the gap this design closes.

## Goals

1. Give the primary LLM classifier a genuine "this isn't a Municipalidad de Rosario
   document" label, strictly scoped so it doesn't become a dumping ground for
   ambiguous-but-real municipal documents.
2. Let `classifier_disagreement()` actually compare `otro` against `otro`, and
   `otro` against a real category, instead of unconditionally returning `False`
   whenever BETO says `otro`.
3. Route a primary-classifier `otro` verdict straight to `human_review`, never
   auto-accepted — mirroring `foreign_municipality`'s existing unconditional
   override in `ConfidenceGateNode.decide()`.
4. Let a primary-vs-BETO disagreement involving `otro` reach the LLM Judge exactly
   like any other disagreement, so the Judge can arbitrate ("BETO's `otro` is right,
   this isn't municipal at all" vs. "the primary's real category is right, BETO
   missed it").

## Non-goals

- No change to `RoutingNode` or document storage folder structure. `otro` always
  routes through `HUMAN_REVIEW` (either directly, or via the Judge which — per the
  existing, unchanged invariant — never auto-accepts a disagreement case), so
  `ReviewRoute.ACCEPT`'s `classified/<label>/` branch is never reached with
  `label="otro"`. No `classified/otro/` folder is ever created by this design.
- No change to `JudgeOutput`'s schema or to the Judge's existing "`final_label` must
  be exactly `primary_label` or `second_opinion_label`, never a third category"
  constraint. That constraint already handles `otro` correctly once it's a valid
  candidate on either side — no special-casing needed.
- No change to BETO/SVM/OOD scoring itself. BETO v2 already predicts `otro`;
  `SecondOpinionResult.label` already returns it raw today. This design only stops
  throwing that signal away.
- No retraining, no change to `models/bert_tunning_beto_v2/` artifacts.

## Decision 1 — `DocumentCategory` gains `OTRO`

**File**: `src/classiflow/classification/domain/categories.py`

Add `OTRO = "otro"` to the enum. Update the class docstring's "10 municipal document
categories" to "11" and note the new category's purpose (out-of-scope/non-municipal
documents) alongside the existing BETO-training-coverage note.

## Decision 2 — Primary classifier prompt gets a strict `otro` definition

**File**: `src/classiflow/classification/prompts/primary_classification.py`

Add one new entry to `_CATEGORY_DEFS`, positioned last (after
`RESOLUCIONES_CONCEJO_MUNICIPAL`) since it's the fallback/exception category, not
part of the normal decreto/resolución/ordenanza taxonomy:

```python
DocumentCategory.OTRO: (
    "Otro: the document is NOT from Municipalidad de Rosario at all -- a "
    "completely different issuing institution (a national government agency, "
    "a bank, a different municipality's own letterhead, a private company). "
    "This is NOT for municipal documents that are merely ambiguous, hard to "
    "categorize, or a poor fit for the 10 categories above -- if the issuer is "
    "genuinely Municipalidad de Rosario (any of its Secretarías, the "
    "Departamento Ejecutivo, or the Concejo Municipal), pick the closest real "
    "category above and reflect any uncertainty with a lower confidence, never "
    "'otro'. Anchor: the document's own letterhead, seal, or issuing-body line "
    "names an institution other than Municipalidad de Rosario -- e.g. \"Banco "
    "Central de la República Argentina\", a different city's municipal "
    "government, a national ministry."
),
```

Add one Rules-block bullet, positioned after the existing "decreto_ordenanzas and
compendios_de_boletines are rare categories" bullet (same "don't over-apply a rare
category" framing):

```
- "otro" is reserved for documents that are not from Municipalidad de Rosario at
all -- wrong issuing institution entirely. Never pick "otro" just because a
genuinely municipal document is confusing or doesn't cleanly match one of the
10 real categories above; in that case pick the closest real category and lower
your confidence instead. Check the document's own letterhead/seal/issuing-body
line before choosing "otro" -- do not infer a non-municipal issuer from topic
or subject matter alone.
```

**Validation**: direct real-model tracing against `A0470.pdf` (confirm it now
classifies as `otro`) and against a sample of genuinely-municipal-but-previously-
tricky documents already traced this session (`resolucion_cm_16879_2024.pdf`,
`decreto_cm_10554_1995.pdf`, the four regression-check documents from the Task 7
prompt-tuning work) to confirm none of them regress to `otro` — the same
trace-then-validate methodology used throughout this session, not a new automated
test (the fix is about real-model interpretation of a strict boundary, matching how
Task 7's Concejo-municipal fix was validated).

## Decision 3 — `classifier_disagreement()` treats `otro` as a normal label

**File**: `src/classiflow/classification/bert/label_mapping.py`

Change `_LABEL_NORMALIZE["otro"]` from `None` to `"otro"`:

```python
_LABEL_NORMALIZE: dict[str, str | None] = {
    "boletines": "boletines",
    "declaracion_concejo_municipal": "declaraciones_concejo_municipal",
    "decreto": "decretos",
    "decreto_ordenanza": "decreto_ordenanzas",
    "decretos_concejo_municipal": "decretos_concejo_municipal",
    "ordenanza": "ordenanzas",
    "resolucion": "resoluciones",
    "resolucion_concejo_municipal": "resoluciones_concejo_municipal",
    "otro": "otro",  # CHANGED -- was None; otro is now a real, comparable category
}
```

`_BETO_TRAINED_LABELS` is derived from `_LABEL_NORMALIZE`'s values
(`frozenset(v for v in _LABEL_NORMALIZE.values() if v is not None)`), so it picks up
`"otro"` automatically — no separate edit needed there.

`classifier_disagreement()`'s body is unchanged — the existing logic
(`normalized != primary_label`, guarded by both sides being in the mappable set)
now naturally produces the desired truth table with no code change to the function
itself:

| `primary_label` | BETO raw | Result |
|---|---|---|
| `otro` | `otro` | `False` (agreement) |
| `otro` | `decreto` | `True` (disagreement — was `False` before this change, since `primary_label not in _BETO_TRAINED_LABELS` used to be true when `otro` wasn't a member; now `otro` IS in the set) |
| `decretos` | `otro` | `True` (disagreement — was `False` before this change, since `normalize_bert_label("otro")` used to return `None`; now returns `"otro"`) |
| `convenios` | `otro` | `False` (unchanged — `convenios` still isn't in `_BETO_TRAINED_LABELS`, BETO was never trained on it, no comparison possible) |

Update the module docstring's stale claim ("BETO v2 was trained on 8 of Classiflow's
10 categories... plus its own 'otro' catch-all with no Classiflow equivalent") to
reflect that `otro` now has a real Classiflow equivalent — BETO was trained on 8 real
categories plus `otro`, and as of this design all 9 of BETO's own labels map onto
Classiflow's taxonomy (`otro` included).

**Testing**: `tests/classification/bert/test_label_mapping.py` already exists and
directly asserts the OLD behavior this decision changes — two tests need updating,
not just extending:
- `test_otro_normalizes_to_none` (asserts `normalize_bert_label("otro") is None`) —
  rename to `test_otro_normalizes_to_itself` and change the assertion to
  `normalize_bert_label("otro") == "otro"`.
- `test_no_disagreement_when_beto_label_is_otro` (asserts
  `classifier_disagreement("decretos", "otro") is False`) — rename to
  `test_disagreement_when_beto_label_is_otro_and_primary_is_a_real_category` and
  change the assertion to `classifier_disagreement("decretos", "otro") is True`.

Add new cases covering the remaining two rows of Decision 3's truth table:
`classifier_disagreement("otro", "otro") is False` and
`classifier_disagreement("otro", "decreto") is True`. Leave
`test_no_disagreement_when_primary_label_outside_beto_taxonomy` (the `convenios`/
`compendios_de_boletines` cases) unchanged — those still correctly return `False`,
unaffected by this decision.

## Decision 4 — `ConfidenceGateNode` routes a primary `otro` label straight to human review

**File**: `src/classiflow/classification/nodes/confidence_gate.py`

`decide()` currently has no visibility into the primary label at all — only
`confidence`, `foreign_municipality`, `classifier_disagreement`. It needs a new
`primary_label: str` keyword parameter, checked as an unconditional override
alongside (but independent from) `foreign_municipality`'s existing one:

```python
async def run(
    self,
    ctx: JobContext,
    *,
    primary_label: str,
    confidence: float,
    foreign_municipality: str | None,
    classifier_disagreement: bool,
) -> ReviewRoute:
    start = await self._emit_started(ctx)
    route = self.decide(
        primary_label=primary_label,
        confidence=confidence,
        foreign_municipality=foreign_municipality,
        classifier_disagreement=classifier_disagreement,
    )
    ...


def decide(
    self,
    *,
    primary_label: str,
    confidence: float,
    foreign_municipality: str | None,
    classifier_disagreement: bool,
) -> ReviewRoute:
    if foreign_municipality is not None:
        return ReviewRoute.HUMAN_REVIEW
    if primary_label == DocumentCategory.OTRO.value:
        return ReviewRoute.HUMAN_REVIEW
    if classifier_disagreement:
        return ReviewRoute.LLM_JUDGE
    if confidence >= self.config.confidence_threshold:
        return ReviewRoute.ACCEPT
    return ReviewRoute.LLM_JUDGE
```

Per the approved design: this check is positioned **before** the
`classifier_disagreement` check, mirroring `foreign_municipality`'s placement —
`otro` alone is sufficient reason for human review; it does not go through the Judge
first. (A primary-`otro`-vs-BETO-real-category *disagreement* still reaches the Judge
normally through the `classifier_disagreement` branch below it — this new check only
fires when the primary itself said `otro`, independent of what BETO said.)

**Coordinator wiring** (`classification/coordinator.py`): `_confidence_gate`'s
closure currently calls `confidence_gate.run(ctx, confidence=state["confidence"],
foreign_municipality=..., classifier_disagreement=...)` — add
`primary_label=state["label"]` to that call. `state["label"]` is already populated
by the time `_confidence_gate` runs (it's set by `_primary_classifier`, several
edges earlier in the graph) — no new state field needed.

**Testing**: `primary_label` becoming a required keyword-only parameter on both
`decide()` and `run()` breaks every existing call site in
`tests/classification/test_confidence_gate_node.py` — all 6 `TestConfidenceGateDecide`
tests and the 1 `TestConfidenceGateRun` test currently omit it entirely. All 7 need
`primary_label="decretos"` (or any real, non-`otro` category) added to their existing
calls so they keep testing what they already test, plus two new cases: `primary_label
="otro"` → `HUMAN_REVIEW` regardless of confidence, and a case confirming
`foreign_municipality` still wins when both `foreign_municipality` and
`primary_label="otro"` fire simultaneously (mirrors the existing
`test_foreign_municipality_wins_over_disagreement` test's shape). Also extend
`tests/classification/test_coordinator.py` with an end-to-end case confirming a
primary-`otro` document reaches `human_review` without visiting the Judge node
(`judged_by_llm` stays `False`/absent) — distinguishing this path from the
disagreement path, which does visit the Judge.

## Decision 5 — LLM Judge gets `otro`'s anchor

**File**: `src/classiflow/classification/prompts/llm_judge.py`

Add one entry to `_CATEGORY_ANCHORS`, condensed from Decision 2's definition,
following the module's own existing convention ("Condensed from
primary_classification.py's `_CATEGORY_DEFS` -- keep these two in sync"):

```python
"otro": (
    "the document is not from Municipalidad de Rosario at all -- a different "
    "issuing institution entirely (national agency, bank, another city's "
    "government). Not for genuinely-municipal documents that are merely "
    "ambiguous between two of the other categories."
),
```

No other change to this file. The existing "`final_label` must be exactly
`primary_label` or `second_opinion_label`, never a third category" instruction
already applies correctly once `otro` is a valid candidate value on either side — the
Judge can conclude either "BETO's `otro` is correct, override the primary's real
category" or "the primary's real category is correct, BETO's `otro` was wrong,"
using the new anchor the same way it already uses the other 10.

**Testing**: no new automated test required beyond Decision 3's `classifier_disagreement`
coverage (which determines whether the Judge is even reached) — the Judge's own
prompt-formatting tests (`test_llm_judge_chain.py`) don't need `otro`-specific cases
since the anchor is rendered the same way every other category's anchor already is,
with no new code path in `_format_prompt`.

## Testing strategy summary

- **Decision 1**: no test — a pure enum addition, exercised transitively by every
  other decision's tests.
- **Decision 2**: real-model tracing (not a new automated test) — validate `A0470.pdf`
  now classifies `otro`, and the existing regression-check document set (from Task 7,
  this session) does not regress to `otro`.
- **Decision 3**: `tests/classification/bert/test_label_mapping.py` (already exists)
  — two existing tests updated to match the new behavior, two new cases added,
  covering all four rows of the truth table.
- **Decision 4**: extended `tests/classification/test_confidence_gate_node.py` (new
  `primary_label="otro"` case, `foreign_municipality`-wins-over-`otro` case) and
  `tests/classification/test_coordinator.py` (end-to-end primary-`otro` reaches
  `human_review` without visiting the Judge).
- **Decision 5**: no new test — covered transitively by Decision 3/4's coverage of
  when the Judge is reached, and the Judge's existing prompt-formatting tests.

## Open questions for the plan

- Whether the module docstring update in `label_mapping.py` (Decision 3) should also
  update the "REVIEW AT END OF STAGE 4" note about `normalize_bert_label`'s single
  caller — out of scope for this design, flagged only so the plan doesn't silently
  drop it if it turns out stale in a way that blocks a clean edit.
- Whether any other test file besides `test_confidence_gate_node.py` constructs
  `ConfidenceGateNode` and calls `.decide()`/`.run()` directly with positional-only
  reliance on the current parameter set (e.g. `test_coordinator.py`'s
  `_build_graph`/`_build_graph_with_disagreement` helpers construct `ConfidenceGateNode`
  itself but call it only through the coordinator graph, not directly — the plan
  should still grep for any other direct `.decide(`/`.run(` call sites before
  editing, in case one was missed in this design's own review.

# Adding `otro` as a Real Document Category Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the primary LLM classifier a genuine "this is not a Municipalidad de
Rosario document" label (`otro`), let disagreement detection actually compare it
against BETO's own `otro` prediction, and route it straight to human review —
closing the gap that let `A0470.pdf` (a Banco Central circular) get silently
auto-accepted as `resoluciones` this session.

**Architecture:** `otro` becomes an 11th value in the shared `DocumentCategory` enum.
`classifier_disagreement()` stops special-casing BETO's `otro` label and treats it as
a normal comparable category. `ConfidenceGateNode` gets a second unconditional
override (alongside the existing `foreign_municipality` one) that routes a
primary-classifier `otro` verdict straight to `HUMAN_REVIEW`, bypassing the judge —
while a primary-vs-BETO disagreement that merely *involves* `otro` on either side
still reaches the judge normally through the existing disagreement path.

**Tech Stack:** Python 3.10, LangGraph (`StateGraph`), Pydantic v2 (`BaseEntity`),
pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-otro-category-design.md`

## Global Constraints

- Line length 100, double quotes, mypy strict (`src/` only) — `uv run poe check`
  after every task.
- Never use `Any`, `from __future__ import annotations`, or `TYPE_CHECKING` unless a
  real circular import forces it.
- Never commit/push/PR without the user's explicit per-message authorization.
- `otro` is reserved strictly for documents that are not from Municipalidad de
  Rosario at all — never for genuinely-municipal documents that are merely
  ambiguous or a poor fit for the other 10 categories. Every prompt-facing change in
  this plan carries that constraint verbatim.
- `otro` always routes through `HUMAN_REVIEW`, never `ACCEPT` — either directly (the
  primary classifier itself said `otro`) or via the judge (a disagreement involving
  `otro` on either side), which per the existing, unchanged invariant never
  auto-accepts a disagreement case.

---

## Task 1: `DocumentCategory` gains `OTRO`

**Files:**
- Modify: `src/classiflow/classification/domain/categories.py`

**Interfaces:**
- Produces: `DocumentCategory.OTRO` with value `"otro"` — consumed by Task 2
  (`_CATEGORY_DEFS`) and Task 4 (`ConfidenceGateNode`).

- [ ] **Step 1: Add the enum member and update the docstring**

Replace:
```python
from enum import Enum


class DocumentCategory(str, Enum):
    """Classiflow's 10 municipal document categories -- canonical label set, sourced
    from README.md's category table. BETO v2 (the Second Opinion Agent,
    classification/bert/) was only ever trained on 8 of these -- COMPENDIOS_DE_BOLETINES
    and CONVENIOS are LLM-only labels. See the BERT spec's Decision 5
    label-normalization map for the full BETO-to-Classiflow correspondence."""

    BOLETINES = "boletines"
    COMPENDIOS_DE_BOLETINES = "compendios_de_boletines"
    CONVENIOS = "convenios"
    DECLARACIONES_CONCEJO_MUNICIPAL = "declaraciones_concejo_municipal"
    DECRETO_ORDENANZAS = "decreto_ordenanzas"
    DECRETOS = "decretos"
    DECRETOS_CONCEJO_MUNICIPAL = "decretos_concejo_municipal"
    ORDENANZAS = "ordenanzas"
    RESOLUCIONES = "resoluciones"
    RESOLUCIONES_CONCEJO_MUNICIPAL = "resoluciones_concejo_municipal"
```
with:
```python
from enum import Enum


class DocumentCategory(str, Enum):
    """Classiflow's 11 document categories -- canonical label set, sourced from
    README.md's category table plus OTRO (added to give the primary classifier an
    escape hatch for documents that are not from Municipalidad de Rosario at all).
    BETO v2 (the Second Opinion Agent, classification/bert/) was only ever trained on
    9 of these -- COMPENDIOS_DE_BOLETINES and CONVENIOS are LLM-only labels. See the
    BERT spec's Decision 5 label-normalization map for the full BETO-to-Classiflow
    correspondence."""

    BOLETINES = "boletines"
    COMPENDIOS_DE_BOLETINES = "compendios_de_boletines"
    CONVENIOS = "convenios"
    DECLARACIONES_CONCEJO_MUNICIPAL = "declaraciones_concejo_municipal"
    DECRETO_ORDENANZAS = "decreto_ordenanzas"
    DECRETOS = "decretos"
    DECRETOS_CONCEJO_MUNICIPAL = "decretos_concejo_municipal"
    ORDENANZAS = "ordenanzas"
    OTRO = "otro"
    RESOLUCIONES = "resoluciones"
    RESOLUCIONES_CONCEJO_MUNICIPAL = "resoluciones_concejo_municipal"
```
(`OTRO` is inserted alphabetically between `ORDENANZAS` and `RESOLUCIONES`, matching
this enum's existing alphabetical-by-value ordering.)

- [ ] **Step 2: Run the full test suite to confirm nothing breaks from the enum addition alone**

Run: `uv run pytest tests/ -v`
Expected: all PASS (nothing references `DocumentCategory.OTRO` yet, and adding an
enum member doesn't change any existing member's value).

- [ ] **Step 3: Commit**

```bash
git add src/classiflow/classification/domain/categories.py
git commit -m "feat: add OTRO to DocumentCategory for non-municipal documents"
```

---

## Task 2: Primary classifier prompt gets a strict `otro` definition

**Files:**
- Modify: `src/classiflow/classification/prompts/primary_classification.py`

**Interfaces:**
- Consumes: `DocumentCategory.OTRO` (Task 1).
- Produces: `_CATEGORY_DEFS[DocumentCategory.OTRO]` and one new `_TEMPLATE` Rules-block
  bullet — no new Python symbols, this task only changes prompt text rendered into
  `_CATEGORIES_BLOCK`/`_TEMPLATE`.

- [ ] **Step 1: Add the `otro` entry to `_CATEGORY_DEFS`**

In `src/classiflow/classification/prompts/primary_classification.py`, add a new
entry after the existing `DocumentCategory.RESOLUCIONES_CONCEJO_MUNICIPAL` entry
(the last one in the dict) and before the closing `}`:

Replace:
```python
    DocumentCategory.RESOLUCIONES_CONCEJO_MUNICIPAL: (
        "Resolución del Concejo Municipal: like decretos_concejo_municipal but "
        "typically parliamentary/procedural matters (commissions, internal Concejo "
        'business). Anchor: opens with "...HA SANCIONADO LA SIGUIENTE: RESOLUCION", '
        "issuing body is 'Concejo Municipal'. This is the hardest pair to separate "
        "from decretos_concejo_municipal -- both share the same 'HA SANCIONADO...' "
        "opening and Concejo issuer; the deciding signal is specifically which noun "
        "(DECRETO vs. RESOLUCION) follows 'HA SANCIONADO EL/LA SIGUIENTE'. Not every "
        "Concejo resolución uses that exact formula -- some instead read '...se "
        "consideró la siguiente: RESOLUCION' or similar committee-referral phrasing. "
        "When the 'HA SANCIONADO...' formula is absent but Concejo Municipal "
        "involvement is otherwise confirmed, the deciding signal is still whichever "
        "noun (DECRETO vs. RESOLUCION/RESOLUCIÓN) names the document's own act type "
        "-- look for it near the document's own number/heading, not only inside the "
        "'HA SANCIONADO' phrase specifically. OCR noise can garble this noun's "
        "spacing or accents (e.g. 'R ES0 LU CIÓN' for 'RESOLUCIÓN') -- read past "
        "such corruption rather than treating a garbled match as absent."
    ),
}
```
with:
```python
    DocumentCategory.RESOLUCIONES_CONCEJO_MUNICIPAL: (
        "Resolución del Concejo Municipal: like decretos_concejo_municipal but "
        "typically parliamentary/procedural matters (commissions, internal Concejo "
        'business). Anchor: opens with "...HA SANCIONADO LA SIGUIENTE: RESOLUCION", '
        "issuing body is 'Concejo Municipal'. This is the hardest pair to separate "
        "from decretos_concejo_municipal -- both share the same 'HA SANCIONADO...' "
        "opening and Concejo issuer; the deciding signal is specifically which noun "
        "(DECRETO vs. RESOLUCION) follows 'HA SANCIONADO EL/LA SIGUIENTE'. Not every "
        "Concejo resolución uses that exact formula -- some instead read '...se "
        "consideró la siguiente: RESOLUCION' or similar committee-referral phrasing. "
        "When the 'HA SANCIONADO...' formula is absent but Concejo Municipal "
        "involvement is otherwise confirmed, the deciding signal is still whichever "
        "noun (DECRETO vs. RESOLUCION/RESOLUCIÓN) names the document's own act type "
        "-- look for it near the document's own number/heading, not only inside the "
        "'HA SANCIONADO' phrase specifically. OCR noise can garble this noun's "
        "spacing or accents (e.g. 'R ES0 LU CIÓN' for 'RESOLUCIÓN') -- read past "
        "such corruption rather than treating a garbled match as absent."
    ),
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
}
```

- [ ] **Step 2: Add the `otro` Rules-block bullet to `_TEMPLATE`**

Replace:
```python
- decreto_ordenanzas and compendios_de_boletines are rare categories -- only \
pick them when their specific anchor (recess/extraordinary-faculty language; \
a range of boletín numbers) is actually present, not just because the text \
resembles a decreto or a boletín.
- An anchor phrase only counts as a signal when it introduces THIS \
```
with:
```python
- decreto_ordenanzas and compendios_de_boletines are rare categories -- only \
pick them when their specific anchor (recess/extraordinary-faculty language; \
a range of boletín numbers) is actually present, not just because the text \
resembles a decreto or a boletín.
- "otro" is reserved for documents that are not from Municipalidad de Rosario at \
all -- wrong issuing institution entirely. Never pick "otro" just because a \
genuinely municipal document is confusing or doesn't cleanly match one of the \
10 real categories above; in that case pick the closest real category and lower \
your confidence instead. Check the document's own letterhead/seal/issuing-body \
line before choosing "otro" -- do not infer a non-municipal issuer from topic \
or subject matter alone.
- An anchor phrase only counts as a signal when it introduces THIS \
```

- [ ] **Step 3: Run the existing MockLlm-based tests to confirm no regression**

Run: `uv run pytest tests/classification/test_primary_classification_chain.py -v`
Expected: all PASS (this task only adds prompt text; the JSON-parsing/chain-building
logic in `build_classification_chain`/`_extract` is untouched).

- [ ] **Step 4: Validate against `A0470.pdf` via real-model tracing**

This is diagnostic, not committed code — use the scratchpad directory. Confirm the
exact session-acquisition helper name via `codegraph_explore("get_session AsyncSession
database engine")` before writing the script (it is `classiflow.database.base.get_session`,
an async generator — iterate it with `async for session in get_session():`, matching
the pattern used throughout this session's diagnostic scripts).

```python
import asyncio

from sqlalchemy import select

from classiflow.classification.config_classification import get_classification_config
from classiflow.classification.prompts.primary_classification import (
    _CATEGORIES_BLOCK,
    _TEMPLATE,
)
from classiflow.database.base import get_session
from classiflow.database.models import EnrichedRecord, Job
from classiflow.ingesta.llm_provider import ChatTemplatedLlamaCpp, _n_gpu_layers
from classiflow.settings import Settings

_TARGETS = [
    "A0470.pdf",
    "resolucion_cm_16879_2024.pdf",
    "decreto_cm_10554_1995.pdf",
    "decreto_cm_1016_2025.pdf",
    "decreto_1000_2008.pdf",
    "resolucion_100_2020.pdf",
]


async def _fetch_text(filename: str) -> str | None:
    async for session in get_session():
        job = (
            await session.execute(select(Job).where(Job.filename == filename))
        ).scalar_one_or_none()
        if job is None:
            return None
        record = (
            await session.execute(select(EnrichedRecord).where(EnrichedRecord.job_id == job.job_id))
        ).scalar_one_or_none()
        return record.cleaned_text if record is not None else None
    return None


def main() -> None:
    texts = {name: asyncio.run(_fetch_text(name)) for name in _TARGETS}
    for name, text in texts.items():
        if text is None:
            print(f"{name}: NOT FOUND")

    llm = ChatTemplatedLlamaCpp(
        model_path=Settings.classification_model_path,
        n_ctx=Settings.slm_n_ctx,
        n_gpu_layers=_n_gpu_layers(),
        max_tokens=Settings.slm_max_tokens,
        temperature=0.0,
        top_p=Settings.slm_top_p,
        seed=Settings.slm_seed,
        verbose=False,
    )
    max_input_tokens = get_classification_config().max_input_tokens

    for name in _TARGETS:
        text = texts.get(name)
        if text is None:
            continue
        excerpt = text[:max_input_tokens]
        prompt = _TEMPLATE.format(categories=_CATEGORIES_BLOCK, cleaned_text=excerpt)
        print(f"\n{'=' * 60}\n{name}\n{'=' * 60}")
        print(llm.invoke(prompt))


if __name__ == "__main__":
    main()
```

Expected: `A0470.pdf` now classifies as `otro`. All five other documents (already
correctly classified per Task 7 of the earlier accuracy-improvements plan) still
classify with their previously-confirmed correct labels — none regress to `otro`. If
any genuinely-municipal document regresses to `otro`, tighten the anchor's wording
(Step 1) and re-trace before proceeding — do not commit a definition that causes a
regression.

- [ ] **Step 5: Commit**

```bash
git add src/classiflow/classification/prompts/primary_classification.py
git commit -m "feat: add strict otro category definition to primary classifier prompt"
```

---

## Task 3: `classifier_disagreement()` treats `otro` as a normal comparable label

**Files:**
- Modify: `src/classiflow/classification/bert/label_mapping.py`
- Test: `tests/classification/bert/test_label_mapping.py`

**Interfaces:**
- Produces: `classifier_disagreement("otro", "otro") == False`,
  `classifier_disagreement("otro", "decreto") == True`,
  `classifier_disagreement("decretos", "otro") == True` (this last one is the exact
  case that let `A0470.pdf` slip through — BETO said `otro`, 0.995 confidence, but
  the primary's `resoluciones` label was never flagged as disagreeing).

- [ ] **Step 1: Update the two existing tests that assert the OLD behavior**

`tests/classification/bert/test_label_mapping.py` currently has two tests that
directly assert the behavior this task changes. Replace:
```python
    def test_otro_normalizes_to_none(self) -> None:
        assert normalize_bert_label("otro") is None
```
with:
```python
    def test_otro_normalizes_to_itself(self) -> None:
        assert normalize_bert_label("otro") == "otro"
```

Replace:
```python
    def test_no_disagreement_when_beto_label_is_otro(self) -> None:
        assert classifier_disagreement("decretos", "otro") is False
```
with:
```python
    def test_disagreement_when_beto_label_is_otro_and_primary_is_a_real_category(self) -> None:
        assert classifier_disagreement("decretos", "otro") is True
```

- [ ] **Step 2: Add two new tests covering the remaining truth-table rows**

Add to `TestClassifierDisagreement` (after the test from Step 1):
```python
def test_agreement_when_both_say_otro(self) -> None:
    assert classifier_disagreement("otro", "otro") is False


def test_disagreement_when_primary_says_otro_and_beto_says_a_real_category(self) -> None:
    assert classifier_disagreement("otro", "decreto") is True
```

- [ ] **Step 3: Run the tests to verify they fail against current code**

Run: `uv run pytest tests/classification/bert/test_label_mapping.py -v`
Expected: `test_otro_normalizes_to_itself` FAILs (`normalize_bert_label("otro")`
currently returns `None`, not `"otro"`).
`test_disagreement_when_beto_label_is_otro_and_primary_is_a_real_category` FAILs
(`classifier_disagreement("decretos", "otro")` currently returns `False`, not
`True`, because `normalize_bert_label("otro")` returning `None` short-circuits the
guard clause).
`test_agreement_when_both_say_otro` does NOT fail — `classifier_disagreement("otro",
"otro")` already returns `False` today, but for the wrong reason: `normalize_bert_label
("otro")` currently returns `None`, so the guard clause's `normalized is None` check
short-circuits to `False` before any real comparison happens — not because the two
labels were actually compared and found equal. This test passes both before and
after Step 4, so it exists to *lock in* the correct end state, not to prove a bug —
skip asserting a fail-before-fix here and note it passes throughout.
`test_disagreement_when_primary_says_otro_and_beto_says_a_real_category` FAILs
(`classifier_disagreement("otro", "decreto")` currently returns `False`, since
`primary_label not in _BETO_TRAINED_LABELS` is true when `otro` isn't a member).

- [ ] **Step 4: Change `_LABEL_NORMALIZE["otro"]` from `None` to `"otro"`**

Replace:
```python
"""BETO-to-Classiflow label normalization -- see the BERT spec's Decision 5. BETO v2 was
trained on 8 of Classiflow's 10 categories (singular Spanish, not plural snake_case) plus
its own "otro" catch-all with no Classiflow equivalent.

REVIEW AT END OF STAGE 4: normalize_bert_label currently has exactly one real caller
(classifier_disagreement, below) -- it's kept as a separate public function only because
it's already exported in bert/__init__.py's __all__ and independently unit-tested, not
because a second consumer exists yet. Once Task 9's SecondOpinionNode is built and its
actual usage is visible, revisit whether normalize_bert_label should stay standalone or
get folded into classifier_disagreement. Per the BERT spec (Decision on
ClassificationRecord fields), second_opinion_label stores BETO's RAW label, not the
normalized one -- so SecondOpinionNode is not expected to call normalize_bert_label
directly either."""

_LABEL_NORMALIZE: dict[str, str | None] = {
    "boletines": "boletines",
    "declaracion_concejo_municipal": "declaraciones_concejo_municipal",
    "decreto": "decretos",
    "decreto_ordenanza": "decreto_ordenanzas",
    "decretos_concejo_municipal": "decretos_concejo_municipal",
    "ordenanza": "ordenanzas",
    "resolucion": "resoluciones",
    "resolucion_concejo_municipal": "resoluciones_concejo_municipal",
    "otro": None,  # BETO's catch-all -- no Classiflow category equivalent
}
```
with:
```python
"""BETO-to-Classiflow label normalization -- see the BERT spec's Decision 5. BETO v2 was
trained on 8 real Classiflow categories (singular Spanish, not plural snake_case) plus
its own "otro" catch-all, which now maps onto Classiflow's own OTRO category too --
all 9 of BETO's labels have a real Classiflow equivalent.

REVIEW AT END OF STAGE 4: normalize_bert_label currently has exactly one real caller
(classifier_disagreement, below) -- it's kept as a separate public function only because
it's already exported in bert/__init__.py's __all__ and independently unit-tested, not
because a second consumer exists yet. Once Task 9's SecondOpinionNode is built and its
actual usage is visible, revisit whether normalize_bert_label should stay standalone or
get folded into classifier_disagreement. Per the BERT spec (Decision on
ClassificationRecord fields), second_opinion_label stores BETO's RAW label, not the
normalized one -- so SecondOpinionNode is not expected to call normalize_bert_label
directly either."""

_LABEL_NORMALIZE: dict[str, str | None] = {
    "boletines": "boletines",
    "declaracion_concejo_municipal": "declaraciones_concejo_municipal",
    "decreto": "decretos",
    "decreto_ordenanza": "decreto_ordenanzas",
    "decretos_concejo_municipal": "decretos_concejo_municipal",
    "ordenanza": "ordenanzas",
    "resolucion": "resoluciones",
    "resolucion_concejo_municipal": "resoluciones_concejo_municipal",
    "otro": "otro",  # otro is now a real, comparable Classiflow category (see Decision 3)
}
```

`_BETO_TRAINED_LABELS` (`frozenset(v for v in _LABEL_NORMALIZE.values() if v is not
None)`) and `classifier_disagreement()`'s body are both unchanged — `_BETO_TRAINED_LABELS`
picks up `"otro"` automatically since it's derived from `_LABEL_NORMALIZE`'s values,
and the existing comparison logic now naturally produces the correct truth table with
no further code change.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/classification/bert/test_label_mapping.py -v`
Expected: all PASS, including the pre-existing
`test_no_disagreement_when_primary_label_outside_beto_taxonomy` (the `convenios`/
`compendios_de_boletines` cases) — unaffected by this change, since those categories
still aren't in `_BETO_TRAINED_LABELS`.

- [ ] **Step 6: Run the broader classification test suite to check for regressions**

Run: `uv run pytest tests/classification/ -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/classiflow/classification/bert/label_mapping.py tests/classification/bert/test_label_mapping.py
git commit -m "feat: classifier_disagreement treats otro as a normal comparable label"
```

---

## Task 4: `ConfidenceGateNode` routes a primary `otro` label straight to human review

**Files:**
- Modify: `src/classiflow/classification/nodes/confidence_gate.py`
- Modify: `src/classiflow/classification/coordinator.py:104-112` (`_confidence_gate` closure)
- Test: `tests/classification/test_confidence_gate_node.py`
- Test: `tests/classification/test_coordinator.py`

**Interfaces:**
- Consumes: `DocumentCategory.OTRO` (Task 1).
- Produces: `ConfidenceGateNode.decide(*, primary_label: str, confidence: float,
  foreign_municipality: str | None, classifier_disagreement: bool) -> ReviewRoute` —
  `primary_label` is a new required keyword parameter. `run()` gains the same
  parameter with the same signature shape.

- [ ] **Step 1: Update all 7 existing call sites in `test_confidence_gate_node.py` to pass `primary_label`**

(Verified via `grep -rn "ConfidenceGateNode" tests/` that `test_pipeline_service_classification.py`,
`test_pipeline_service_enrichment.py`, and `test_coordinator.py` only ever
*construct* `ConfidenceGateNode(...)` and exercise it through the full coordinator
graph — none call `.decide()`/`.run()` directly. `test_confidence_gate_node.py` is
the only file with direct calls, so it's the only one needing this update.)

Every existing `.decide(...)` and `.run(...)` call in this file currently omits
`primary_label` entirely and will break once it becomes required. Replace the whole
file's test bodies (keeping every existing test's name, intent, and assertion
unchanged) — add `primary_label="decretos"` to each of the 7 existing calls:

Replace:
```python
class TestConfidenceGateDecide:
    def test_foreign_municipality_routes_to_human_review_regardless_of_confidence(self) -> None:
        route = _node().decide(
            confidence=0.99, foreign_municipality="Cordoba", classifier_disagreement=False
        )
        assert route == "human_review"

    def test_classifier_disagreement_routes_to_llm_judge_regardless_of_confidence(self) -> None:
        route = _node().decide(
            confidence=0.99, foreign_municipality=None, classifier_disagreement=True
        )
        assert route == "llm_judge"

    def test_foreign_municipality_wins_over_disagreement(self) -> None:
        route = _node().decide(
            confidence=0.99, foreign_municipality="Cordoba", classifier_disagreement=True
        )
        assert route == "human_review"

    def test_high_confidence_with_no_flags_accepts(self) -> None:
        route = _node().decide(
            confidence=0.9, foreign_municipality=None, classifier_disagreement=False
        )
        assert route == "accept"

    def test_confidence_exactly_at_threshold_accepts(self) -> None:
        route = _node().decide(
            confidence=0.75, foreign_municipality=None, classifier_disagreement=False
        )
        assert route == "accept"

    def test_low_confidence_with_no_flags_goes_to_llm_judge(self) -> None:
        route = _node().decide(
            confidence=0.5, foreign_municipality=None, classifier_disagreement=False
        )
        assert route == "llm_judge"


class TestConfidenceGateRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = ConfidenceGateNode(
            audit=AuditService(audit_repo), broadcaster=broadcaster, config=_CONFIG
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        route = await node.run(
            ctx, confidence=0.9, foreign_municipality=None, classifier_disagreement=False
        )
        assert route == "accept"
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"
```
with:
```python
class TestConfidenceGateDecide:
    def test_foreign_municipality_routes_to_human_review_regardless_of_confidence(self) -> None:
        route = _node().decide(
            primary_label="decretos",
            confidence=0.99,
            foreign_municipality="Cordoba",
            classifier_disagreement=False,
        )
        assert route == "human_review"

    def test_classifier_disagreement_routes_to_llm_judge_regardless_of_confidence(self) -> None:
        route = _node().decide(
            primary_label="decretos",
            confidence=0.99,
            foreign_municipality=None,
            classifier_disagreement=True,
        )
        assert route == "llm_judge"

    def test_foreign_municipality_wins_over_disagreement(self) -> None:
        route = _node().decide(
            primary_label="decretos",
            confidence=0.99,
            foreign_municipality="Cordoba",
            classifier_disagreement=True,
        )
        assert route == "human_review"

    def test_high_confidence_with_no_flags_accepts(self) -> None:
        route = _node().decide(
            primary_label="decretos",
            confidence=0.9,
            foreign_municipality=None,
            classifier_disagreement=False,
        )
        assert route == "accept"

    def test_confidence_exactly_at_threshold_accepts(self) -> None:
        route = _node().decide(
            primary_label="decretos",
            confidence=0.75,
            foreign_municipality=None,
            classifier_disagreement=False,
        )
        assert route == "accept"

    def test_low_confidence_with_no_flags_goes_to_llm_judge(self) -> None:
        route = _node().decide(
            primary_label="decretos",
            confidence=0.5,
            foreign_municipality=None,
            classifier_disagreement=False,
        )
        assert route == "llm_judge"

    def test_primary_label_otro_routes_to_human_review_regardless_of_confidence(self) -> None:
        route = _node().decide(
            primary_label="otro",
            confidence=0.99,
            foreign_municipality=None,
            classifier_disagreement=False,
        )
        assert route == "human_review"

    def test_foreign_municipality_wins_over_otro(self) -> None:
        route = _node().decide(
            primary_label="otro",
            confidence=0.99,
            foreign_municipality="Cordoba",
            classifier_disagreement=False,
        )
        assert route == "human_review"


class TestConfidenceGateRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = ConfidenceGateNode(
            audit=AuditService(audit_repo), broadcaster=broadcaster, config=_CONFIG
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        route = await node.run(
            ctx,
            primary_label="decretos",
            confidence=0.9,
            foreign_municipality=None,
            classifier_disagreement=False,
        )
        assert route == "accept"
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"
```

- [ ] **Step 2: Run the tests to verify they fail against current code**

Run: `uv run pytest tests/classification/test_confidence_gate_node.py -v`
Expected: every test FAILs with a `TypeError` (`decide()`/`run()` got an unexpected
keyword argument `primary_label`) — `primary_label` isn't a parameter yet.

- [ ] **Step 3: Add `primary_label` to `ConfidenceGateNode.decide()` and `run()`**

Replace:
```python
async def run(
    self,
    ctx: JobContext,
    *,
    confidence: float,
    foreign_municipality: str | None,
    classifier_disagreement: bool,
) -> ReviewRoute:
    start = await self._emit_started(ctx)
    route = self.decide(
        confidence=confidence,
        foreign_municipality=foreign_municipality,
        classifier_disagreement=classifier_disagreement,
    )
    await self._emit_and_audit(
        ctx,
        start,
        passed=True,
        detail=AuditDetail.model_validate({
            "filename": ctx.filename,
            "review_route": route.value,
        }),
    )
    return route


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
with:
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
    await self._emit_and_audit(
        ctx,
        start,
        passed=True,
        detail=AuditDetail.model_validate({
            "filename": ctx.filename,
            "review_route": route.value,
        }),
    )
    return route


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

Add the import at the top of the file:
```python
from classiflow.classification.domain.categories import DocumentCategory
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/classification/test_confidence_gate_node.py -v`
Expected: all PASS, including the two new `otro` cases.

- [ ] **Step 5: Wire `primary_label` through the coordinator's `_confidence_gate` closure**

In `src/classiflow/classification/coordinator.py`, replace:
```python
    async def _confidence_gate(state: ClassificationState) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        route = await confidence_gate.run(
            ctx,
            confidence=state["confidence"],
            foreign_municipality=state.get("foreign_municipality"),
            classifier_disagreement=state.get("classifier_disagreement", False),
        )
        return _dump(ClassificationUpdate(review_route=route))
```
with:
```python
    async def _confidence_gate(state: ClassificationState) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        route = await confidence_gate.run(
            ctx,
            primary_label=state["label"],
            confidence=state["confidence"],
            foreign_municipality=state.get("foreign_municipality"),
            classifier_disagreement=state.get("classifier_disagreement", False),
        )
        return _dump(ClassificationUpdate(review_route=route))
```
`state["label"]` is already populated by the time `_confidence_gate` runs — it's set
by `_primary_classifier`, which runs several edges earlier in the graph
(`primary_classifier → second_opinion → foreign_municipality → smells_risk →
confidence_gate`). No new `ClassificationState`/`ClassificationUpdate` field is
needed.

- [ ] **Step 6: Add an end-to-end coordinator test for the primary-`otro` path**

Add to `tests/classification/test_coordinator.py`, in a new test class after
`TestClassificationCoordinatorHumanReviewPath` (before the `_DisagreeingClassifier`
class):
```python
_OTRO_HIGH_CONFIDENCE_RESPONSE = (
    '{"label": "otro", "confidence": 0.9, "reasoning": "not a municipal document"}'
)


class TestClassificationCoordinatorOtroPath:
    async def test_primary_otro_routes_to_human_review_without_visiting_judge(
        self, tmp_path: Path
    ) -> None:
        graph, repo = _build_graph(_OTRO_HIGH_CONFIDENCE_RESPONSE, tmp_path)
        job_id = "coord-otro-001"
        filename = "banco_central_circular.pdf"
        _stage_file(tmp_path, job_id, filename)
        initial: ClassificationState = {
            "job_id": job_id,
            "filename": filename,
            "cleaned_text": "Banco Central de la República Argentina, Comunicación A 470.",
            "enriched_id": 1,
        }
        result = await graph.ainvoke(initial)

        assert result["review_route"] == "human_review"
        # judged_by_llm is only ever set when the llm_judge branch actually ran
        # (ClassificationState is total=False) -- absent here proves the otro
        # override skipped the judge entirely, distinguishing this path from the
        # disagreement path (which does visit the judge).
        assert result.get("judged_by_llm", False) is False
        assert Path("review", "human_review").as_posix() in Path(result["stored_path"]).as_posix()

        record = await repo.find_by_job_id(job_id)
        assert record is not None
        assert record.review_route == "human_review"
        assert record.label == "otro"
        assert record.judged_by_llm is False
```
(`_build_graph` uses `second_opinion_enabled=False`, so no `SecondOpinionResult` is
needed here — this test isolates the primary-`otro`-alone override from Task 3's
disagreement-comparison behavior, which is already covered by the unit tests in
Task 3 and the existing `TestClassificationCoordinatorDisagreementPath` tests.)

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv run pytest tests/classification/test_coordinator.py -v`
Expected: all PASS, including the new `TestClassificationCoordinatorOtroPath` test.

- [ ] **Step 8: Run the full test suite and `uv run poe check`**

Run: `uv run pytest tests/ -v`
Expected: all PASS.

Hand `uv run poe check` to the user per this project's execution-workflow rule, or
run directly if you have execution permission for non-notebook commands in this
session.
Expected: all steps (lint, typecheck) PASS.

- [ ] **Step 9: Commit**

```bash
git add src/classiflow/classification/nodes/confidence_gate.py src/classiflow/classification/coordinator.py tests/classification/test_confidence_gate_node.py tests/classification/test_coordinator.py
git commit -m "feat: route primary-classifier otro verdicts straight to human review"
```

---

## Task 5: LLM Judge gets `otro`'s anchor

**Files:**
- Modify: `src/classiflow/classification/prompts/llm_judge.py`

**Interfaces:**
- Produces: `_CATEGORY_ANCHORS["otro"]` — rendered into the judge's prompt via
  `_format_prompt` exactly like every other category's anchor, no new code path.

- [ ] **Step 1: Add the `otro` anchor to `_CATEGORY_ANCHORS`**

Replace:
```python
    "resoluciones_concejo_municipal": (
        '"...HA SANCIONADO LA SIGUIENTE: RESOLUCION" -- issuing body is Concejo Municipal, '
        "on parliamentary/internal Concejo matters (not RESUELVE verb -- that's the "
        "executive resoluciones anchor)"
    ),
}
```
with:
```python
    "resoluciones_concejo_municipal": (
        '"...HA SANCIONADO LA SIGUIENTE: RESOLUCION" -- issuing body is Concejo Municipal, '
        "on parliamentary/internal Concejo matters (not RESUELVE verb -- that's the "
        "executive resoluciones anchor)"
    ),
    "otro": (
        "the document is not from Municipalidad de Rosario at all -- a different "
        "issuing institution entirely (national agency, bank, another city's "
        "government). Not for genuinely-municipal documents that are merely "
        "ambiguous between two of the other categories."
    ),
}
```

No other change to this file — the existing "`final_label` must be exactly
`primary_label` or `second_opinion_label`, never a third category" instruction in
`_TEMPLATE` already applies correctly once `otro` is a valid candidate value on
either side; `_format_prompt` renders `_CATEGORY_ANCHORS_BLOCK` the same way
regardless of which keys it contains, so no code change is needed beyond the dict
entry itself.

- [ ] **Step 2: Run the existing judge prompt tests to confirm no regression**

Run: `uv run pytest tests/classification/test_llm_judge_chain.py tests/classification/test_llm_judge_node.py -v`
Expected: all PASS (this task only adds one dict entry rendered into the same
`_CATEGORIES_ANCHORS_BLOCK` string-join every existing test already exercises).

- [ ] **Step 3: Run the full test suite and `uv run poe check`**

Run: `uv run pytest tests/ -v`
Expected: all PASS.

Hand `uv run poe check` to the user or run directly if permitted.
Expected: all steps PASS.

- [ ] **Step 4: Commit**

```bash
git add src/classiflow/classification/prompts/llm_judge.py
git commit -m "feat: LLM judge prompt gains the otro category anchor"
```

---

## Final verification

- [ ] Run `uv run pytest tests/ -v` — all tests pass, including every new/updated
  test across Tasks 3-4.
- [ ] Run `uv run poe check` (lint + typecheck) — hand to the user per this
  project's execution-workflow rule, or run directly if permitted.
- [ ] Run `uv run --all-groups pre-commit run --all-files` before requesting PR
  authorization, per this project's PR authorization protocol in `CLAUDE.md`.
- [ ] Manually re-run the end-to-end notebook
  (`uv run jupyter execute src/classiflow/playground/stage4/full_pipeline_end_to_end.ipynb`,
  handed to the user per the execution-workflow rule) with `A0470.pdf` still in
  `_SAMPLE_FILES` (expected label `"otro"`) and confirm the report now shows it
  correctly classified as `otro` and routed to `human_review`, instead of the
  `row-wrong-uncaught` outcome observed earlier this session.
- [ ] Present the change summary (each file touched, what changed, test results)
  and ask "Do you authorize the PR creation?" before running any `git commit`/
  `git push`/`gh pr create` beyond the per-task commits already made during
  development — per `CLAUDE.md`'s PR authorization protocol, task-level commits
  during development are expected, but opening a PR against the branch still needs
  explicit authorization.

# Routing operations — implementation plan

Design: `docs/superpowers/specs/2026-09-07-routing-operations-design.md`

Modified: `classification/nodes/routing.py`, `api/routes/classification/endpoints.py`.
The coordinator and `RoutingInput` are **not** touched — that is the property this plan
preserves.

## Global constraints

- No `Any`, no `# noqa`, no `from __future__ import annotations`, no widening the lint
  config to avoid restructuring.
- `RoutingInput` and `coordinator.py:_routing` stay exactly as they are. If either needs a
  change, the design was wrong — stop and revisit the spec.
- No schema change. No migration.
- The three "a human decision must not erase history" tests must pass unedited throughout:
  `test_override_preserves_the_machine_prediction`,
  `test_override_preserves_the_original_machine_route`,
  `test_override_preserves_the_judge_verdict`. They are the regression net.
- Run `uv run poe check` after each task.
- Do not stage, commit, push, or open a PR without explicit authorization.

## Task 1: Characterize what the endpoints write today

Before moving the writes, pin their result. Without this the migration cannot prove nothing
changed.

**Files:** modify `tests/api/routes/test_classification.py`

- [x] Seed a record with every field populated to a distinct, recognizable value —
  including the ones `_reroute` currently restates and the two it proved dead
  (`machine_review_route`, `expected_label`).
- [x] Assert the full record state after a decision: which fields changed, which did not.
  Name every field explicitly; this is the one place a field list is the point.
- [x] The same for a reopen.
- [x] Both pass against the current code, before any refactor.

```bash
uv run pytest tests/api/routes/test_classification.py -v
```

If either fails now, the assertion is wrong about today's behaviour — fix the test, not the
production code.

**Done 2026-09-07.** `TestHumanPathsPreserveEveryUnownedField`, two tests, 18 marked
fields each. Verified by sabotage: dropping `judge_reasoning` from `_reroute` fails both
with `judge_reasoning was not preserved`.

Found while writing them: `ood_metrics` is **not** preserved verbatim. `_reroute`
re-validates the stored dict through `OodMetrics` and dumps it back, so a partial dict
comes out enriched with five defaulted fields. The assertion spells out the full shape
rather than pretending the round-trip does not happen -- and Task 2 should decide whether
the operations keep that behaviour or read the column straight through.

**Suggested commit boundary:** characterize the record state each human path writes.

## Task 2: Add the two operations

**Files:** modify `src/classiflow/classification/nodes/routing.py`

- [x] Add `apply_human_decision(ctx, job_id, *, label, original_label)`. It loads the
  record via `self.classification_repo` — the node already holds it (`routing.py:20-29`)
  and already loads at `:66`.
- [x] Add `reopen_for_review(ctx, job_id)`. It takes **no** `original_label`: the
  fabrication bug is unrepresentable when the parameter does not exist.
- [x] Both set `review_route` and `human_overridden` themselves — `ACCEPT`/`True` for a
  decision, `HUMAN_REVIEW`/unchanged for a reopen — and touch nothing else.
- [x] Both return `RoutingResult`, since both move the file.
- [x] Extract the shared file-move-and-save into a private helper if the two bodies
  duplicate it; do **not** reintroduce a flag argument to share more than that.
- [x] `run()` keeps its exact signature. The machine pass must not notice this task.

At this point nothing calls the new methods. Deliberate — they land green and reviewable on
their own.

```bash
uv run pytest tests/classification/test_routing_node.py -v
```

**Done 2026-09-07.** Both operations added, plus `_load` and `_file_and_save` as the
shared helper. Reused the existing `ClassificationRecordNotFoundError` rather than adding
a new exception. `run()` and `_save_record` are untouched, so the machine pass is
unaffected -- `git diff` on `coordinator.py` and `domain/results.py` is empty.

`ood_metrics` (the Task 1 finding): the operations never touch the column, so no
round-trip happens on their path. Task 3 will change that behaviour for the endpoints --
the enrichment Task 1 characterized comes from `_reroute`, which is about to be deleted.

**Suggested commit boundary:** two named routing operations, not yet wired.

## Task 3: Wire the endpoints, delete `_reroute`

**Files:** modify `src/classiflow/api/routes/classification/endpoints.py`

- [x] `submit_classification_decision` calls `apply_human_decision`, passing
  `original_label=record.original_label or record.label` — the same expression
  `capture_prediction=True` produced, now visible at the call site instead of hidden behind
  a flag.
- [x] `reopen_classification` calls `reopen_for_review`.
- [x] Delete `_reroute` and the `capture_prediction` parameter entirely.
- [x] Leave the precondition guards, the exception types, the audit writes and
  `require_admin` exactly where they are. They already differ between the two paths and are
  not part of this change.
- [x] Check whether `OodMetrics` is still imported in this module — `_reroute` was its only
  consumer here, and ticket 01 found its round-trip through `_reroute` was pure ceremony.

```bash
uv run pytest tests/api/routes/test_classification.py -v
```

Task 1's characterization tests must pass **unedited**. If they need changing, the
operations write something different from what the endpoints wrote, and that is a bug in
Task 2 — not a test to update.

**Done 2026-09-07.** `_reroute` and `capture_prediction` deleted; ruff removed the
imports they were the only consumer of, including `OodMetrics` -- so the dict-to-model
round-trip ticket 01 flagged as ceremony is gone with them.

Task 1's characterization tests passed **unedited**, which is the check that mattered: the
operations write exactly what `_reroute` wrote. Only a comment in that file changed, and
only because it described code that no longer exists.

Endpoints lost 78 lines, gained 12.

**Suggested commit boundary:** endpoints call routing operations; `_reroute` deleted.

## Task 4: Prove the bug class is gone

The point of the refactor, made checkable.

**Files:** modify `tests/api/routes/test_classification.py`

- [x] Rewrite the `_decided_job` helper (`:136-144`) to call the decision endpoint instead
  of hand-mutating four fields. It reaches past the interface today only because no
  "decide" operation existed.
- [x] Add a test that decides and then reopens the same record, asserting history survives
  both. Nothing currently covers that sequence — it is how the `original_label`
  fabrication reached production.
- [x] **The honest check:** add a 25th field to `RoutingInput` locally, run the suite, and
  confirm no human-path test fails and no human-path record is corrupted. Then revert the
  field. If something breaks, the operations still name fields they should not.

Record the result of that last check in the spec, whatever it is.

**Done 2026-09-07. The bug class is gone.**

Added a 25th field (`sabotage_signal`) to both `ClassificationRecord` and `RoutingInput`,
seeded a record with it set, and decided through the endpoint:

- **New code: passes.** The operations never name the field, so they cannot zero it.
- **Old code: fails.** Reverting the endpoint to build a `RoutingInput` by hand and call
  `run()` -- omitting the new field exactly as `_reroute` would have -- writes `None` over
  the live value.

That is the whole argument for the refactor, made executable. Everything was reverted
afterwards; `grep -rn sabotage src/ tests/` is clean.

`_decided_job` now decides through the endpoint instead of hand-mutating four fields, and
the decision→reopen→re-decide sequence was already covered by
`test_a_reopened_record_can_be_decided_again`.

**Suggested commit boundary:** the decision→reopen sequence, and the bug-class check.

## Final verification

```bash
uv run poe check
```

- [x] `git diff` touches only `routing.py`, `endpoints.py`, and
  `tests/api/routes/test_classification.py`.
- [x] `coordinator.py` and `domain/results.py` are untouched.
- [x] `grep -n "capture_prediction\|_reroute" src/` returns nothing.
- [x] The three history-preservation tests pass with no edits since before Task 1, plus
  `test_history_fields_survive_a_reopen`. Confirmed by diffing the test file: none of the
  four appears in the diff.

**652 passed, 12 pre-commit hooks green.** Endpoints: -70 lines, +8.

## Not in this plan

**`ClassificationUpdate` / `ClassificationState`.** Two more parallel field lists mirroring
`RoutingInput`. They belong to the LangGraph state contract, not to routing, and collapsing
them is a separate question.

**Moving the audit write into the operations.** The endpoints write it before calling
routing so a reopen's entry survives a routing failure. Left alone; see the spec's open
question.

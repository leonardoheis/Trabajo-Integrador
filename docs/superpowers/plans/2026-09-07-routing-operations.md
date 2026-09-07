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

- [ ] Seed a record with every field populated to a distinct, recognizable value —
  including the ones `_reroute` currently restates and the two it proved dead
  (`machine_review_route`, `expected_label`).
- [ ] Assert the full record state after a decision: which fields changed, which did not.
  Name every field explicitly; this is the one place a field list is the point.
- [ ] The same for a reopen.
- [ ] Both pass against the current code, before any refactor.

```bash
uv run pytest tests/api/routes/test_classification.py -v
```

If either fails now, the assertion is wrong about today's behaviour — fix the test, not the
production code.

**Suggested commit boundary:** characterize the record state each human path writes.

## Task 2: Add the two operations

**Files:** modify `src/classiflow/classification/nodes/routing.py`

- [ ] Add `apply_human_decision(ctx, job_id, *, label, original_label)`. It loads the
  record via `self.classification_repo` — the node already holds it (`routing.py:20-29`)
  and already loads at `:66`.
- [ ] Add `reopen_for_review(ctx, job_id)`. It takes **no** `original_label`: the
  fabrication bug is unrepresentable when the parameter does not exist.
- [ ] Both set `review_route` and `human_overridden` themselves — `ACCEPT`/`True` for a
  decision, `HUMAN_REVIEW`/unchanged for a reopen — and touch nothing else.
- [ ] Both return `RoutingResult`, since both move the file.
- [ ] Extract the shared file-move-and-save into a private helper if the two bodies
  duplicate it; do **not** reintroduce a flag argument to share more than that.
- [ ] `run()` keeps its exact signature. The machine pass must not notice this task.

At this point nothing calls the new methods. Deliberate — they land green and reviewable on
their own.

```bash
uv run pytest tests/classification/test_routing_node.py -v
```

**Suggested commit boundary:** two named routing operations, not yet wired.

## Task 3: Wire the endpoints, delete `_reroute`

**Files:** modify `src/classiflow/api/routes/classification/endpoints.py`

- [ ] `submit_classification_decision` calls `apply_human_decision`, passing
  `original_label=record.original_label or record.label` — the same expression
  `capture_prediction=True` produced, now visible at the call site instead of hidden behind
  a flag.
- [ ] `reopen_classification` calls `reopen_for_review`.
- [ ] Delete `_reroute` and the `capture_prediction` parameter entirely.
- [ ] Leave the precondition guards, the exception types, the audit writes and
  `require_admin` exactly where they are. They already differ between the two paths and are
  not part of this change.
- [ ] Check whether `OodMetrics` is still imported in this module — `_reroute` was its only
  consumer here, and ticket 01 found its round-trip through `_reroute` was pure ceremony.

```bash
uv run pytest tests/api/routes/test_classification.py -v
```

Task 1's characterization tests must pass **unedited**. If they need changing, the
operations write something different from what the endpoints wrote, and that is a bug in
Task 2 — not a test to update.

**Suggested commit boundary:** endpoints call routing operations; `_reroute` deleted.

## Task 4: Prove the bug class is gone

The point of the refactor, made checkable.

**Files:** modify `tests/api/routes/test_classification.py`

- [ ] Rewrite the `_decided_job` helper (`:136-144`) to call the decision endpoint instead
  of hand-mutating four fields. It reaches past the interface today only because no
  "decide" operation existed.
- [ ] Add a test that decides and then reopens the same record, asserting history survives
  both. Nothing currently covers that sequence — it is how the `original_label`
  fabrication reached production.
- [ ] **The honest check:** add a 25th field to `RoutingInput` locally, run the suite, and
  confirm no human-path test fails and no human-path record is corrupted. Then revert the
  field. If something breaks, the operations still name fields they should not.

Record the result of that last check in the spec, whatever it is.

**Suggested commit boundary:** the decision→reopen sequence, and the bug-class check.

## Final verification

```bash
uv run poe check
```

- [ ] `git diff` touches only `routing.py`, `endpoints.py`, and
  `tests/api/routes/test_classification.py`.
- [ ] `coordinator.py` and `domain/results.py` are untouched.
- [ ] `grep -n "capture_prediction\|_reroute" src/` returns nothing.
- [ ] The three history-preservation tests pass with no edits since before Task 1.

## Not in this plan

**`ClassificationUpdate` / `ClassificationState`.** Two more parallel field lists mirroring
`RoutingInput`. They belong to the LangGraph state contract, not to routing, and collapsing
them is a separate question.

**Moving the audit write into the operations.** The endpoints write it before calling
routing so a reopen's entry survives a routing failure. Left alone; see the spec's open
question.

# Accuracy Metrics Review Remediation

**Date:** 2026-09-03  
**Branch reviewed:** `docs/accuracy-measurement-plan`  
**Review base:** `origin/main` at `01f1cbc86053cac49cd889038e386a3321179a43`

## Context

The accuracy-measurement branch adds filename-derived ground truth, accuracy reporting,
an API endpoint, a metrics page, and a CLI report. It also includes unrelated logout,
model-lifecycle, and sidebar changes.

The existing automated checks pass, but the review found correctness problems that can
make the reported metrics inaccurate and a concurrency problem that can unload the chat
model while it is still in use.

## Goals

1. Preserve whether the classification safety net originally escalated a prediction.
2. Treat explicit human adjudication as stronger ground truth than a filename convention.
3. Prevent logout from unloading a model used by an active generation.
4. Make historical accuracy data available after a normal database upgrade.
5. Align new code with the repository's comment and domain-model conventions.

## Non-goals

- Changing the classifier, prompts, confidence thresholds, or category taxonomy.
- Recomputing model predictions for historical documents.
- Redesigning the metrics page.
- Changing authentication token invalidation semantics.

## Requirements

### R1. Preserve historical safety-net decisions

The metrics service must determine whether a wrong prediction was caught from the route
selected when the machine classification was first produced. It must not infer that fact
from the mutable route stored after a reviewer resolves the item.

- Persist the original machine-selected review route or an equivalent immutable
  `was_escalated` value.
- A human decision may update the record's current workflow route without changing the
  historical safety-net value.
- Repeated updates must preserve the first machine decision.
- `wrong_caught`, `wrong_uncaught`, and `safeguarded_accuracy` must use the historical
  value.

### R2. Prioritize human ground truth

When a record contains a valid human correction and its original machine prediction was
preserved:

- The reviewer's current label is the ground truth.
- `original_label` is the machine prediction being evaluated.
- A filename-derived `expected_label` must not override the human decision.

For records without a human correction, `expected_label` remains the ground truth.
Records with neither source remain excluded from accuracy denominators.

**A human correction whose original prediction was not preserved must be excluded even when
`expected_label` exists.** For such records `label` holds the reviewer's answer and the
machine's prediction is unrecoverable, so the only comparison available is reviewer vs.
filename — which measures nothing about the classifier. At review time this affects all 13
historical corrections, and they are currently *included*, contaminating the reported strict
accuracy. Fixing precedence alone does not address this; the exclusion is a separate rule.

### R3. Make chat-model unloading concurrency-safe

A per-user logout must not reset process-wide generation state or unload the shared
llama.cpp model while any generation is active.

- Remove the unconditional global generation-counter reset from logout.
- Keep unload guarded by the real number of active generations.
- Repair stream cleanup at the stream lifecycle boundary, not from logout. The mechanism:
  - Starlette's `StreamingResponse` does not `aclose()` its body iterator on client
    disconnect (it relies on `OSError` from `send()`), so cleanup must be explicit: wrap
    the generator in `contextlib.aclosing` and close it in a response-level `finally`.
  - Give the producer thread a cooperative stop event, checked between emitted tokens, so
    a disconnected consumer stops the blocking llama.cpp loop instead of letting it run to
    completion holding the counter.
  - `_stream_tokens()` decrements exactly once, in its own `finally`.
  - `request.is_disconnected()` alone is insufficient — it is polling and may observe the
    disconnect only after another token is produced.
  - A timestamp-based reaper is rejected: it cannot distinguish a stale generation from a
    legitimately slow one and would recreate the live-model eviction race.
- Counter underflow must remain impossible, but clamping must not hide lifecycle defects.

### R4. Backfill existing classification records

Upgrading an existing installation must not leave all historical records unlabelled when
their associated filenames identify a supported category.

- Add a migration or explicit upgrade-time backfill that derives `expected_label` from the
  related job filename using the same mapping as new classifications.
- Preserve existing non-null values.
- Leave unmatched filenames as `NULL`.
- The behavior must work without relying on the checked-in development database.
- If a migration backfill is intentionally rejected, documentation and UI must explicitly
  state that metrics only cover classifications created after the upgrade.

### R5. Separate unrelated work

The accuracy feature should not depend on sidebar responsiveness changes or unsafe model
lifecycle changes.

- Move unrelated UI styling and logout/model-lifecycle work to separate changes or commits.
- Keep any model-lifecycle change independently reviewable and covered by concurrency
  tests.

### R6. Align comments and types with repository conventions

- Reduce long implementation-history comments and docstrings to short explanations of
  invariants or intent. Keep extended rationale in `docs/accuracy-metrics.md`.
- Use `DocumentCategory` and `ReviewRoute` within the Python service/domain layer where
  practical, serializing them to strings only at the API boundary.
- Replace ambiguous callback names such as `c`, `e`, and `p` in metrics UI calculations.
- Prevent backend/frontend contract drift. Code generation is deferred: for one endpoint the
  build step outweighs the benefit. The accepted compromise, with its residual risk named:
  - Keep the handwritten `AccuracyReport` TypeScript interface.
  - Add a backend test asserting the `/classification/metrics` OpenAPI schema (field names,
    required set, camelCase aliases).
  - Add a frontend fixture typed with `satisfies AccuracyReport`, built from a real API
    response, so a renamed or removed field fails `tsc`.
  - Neither test alone links the two contracts; together they catch a rename on either side
    but not a simultaneous coordinated drift. Revisit generation if the API surface grows.

## Acceptance criteria

- Resolving a human-review item does not change whether its original miss counts as
  caught.
- A human-corrected record with an `expected_label` is scored against the human label.
- A human-corrected record with no `original_label` is excluded from every accuracy rate,
  regardless of `expected_label`.
- Logging out during another active chat generation does not reset its activity state or
  unload its model.
- A database upgraded from revision `0013` exposes historical filename-derived labels
  after revision `0014` or a replacement migration runs.
- Unmatched historical filenames remain excluded from the accuracy denominator.
- The metrics CLI, API, and UI report identical totals and rates from the same database.
- Ruff, strict mypy, backend tests, frontend tests, and the frontend production build pass.

## Required regression tests

1. A wrong prediction initially routed to human review remains `wrong_caught` after the
   reviewer accepts or overrides it.
2. A record containing both filename ground truth and a human correction uses the human
   label as truth and `original_label` as the prediction.
2b. A record with `human_overridden=true`, `original_label=NULL` and a non-null
   `expected_label` is excluded from `labelled` and from every rate.
3. Logout while an independent generation is active does not call model eviction.
4. Completing, failing, or cancelling a stream decrements activity exactly once; a
   consumer that abandons the stream mid-generation still releases the counter.
5. Migration from an `0013` fixture backfills recognized filenames, preserves existing
   values, and leaves unknown filenames null.
6. The frontend metrics contract matches the API response shape.

## Validation commands

```bash
uv run poe lint
uv run poe typecheck
uv run poe test
cd src/classiflow/frontend
npm run build
npm run test -- --run
```

## Review notes

At the time of the review, all existing checks passed: Ruff, strict mypy, 558 backend
tests, 30 frontend tests, and the frontend production build. Those results do not cover
the historical-route, human-ground-truth precedence, migration-backfill, or concurrent
logout scenarios specified above.

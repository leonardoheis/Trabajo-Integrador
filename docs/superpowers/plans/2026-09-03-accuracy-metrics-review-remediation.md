# Accuracy Metrics Review Remediation Implementation Plan

> **For implementers:** Work task-by-task and keep the checkboxes current. Write the
> regression test first for each behavioral change. Suggested commit boundaries are
> documented, but no commit, push, or PR is authorized by this plan.

**Goal:** Make accuracy reporting historically correct, preserve the safety-net decision
that existed before human review, repair the unsafe logout/model-unload interaction, and
align the feature with repository conventions.

**Architecture:** Add an immutable `machine_review_route` alongside the mutable workflow
`review_route`. `MetricsService` will evaluate human-corrected records against the human
label and will calculate safety-net performance from `machine_review_route`. A follow-up
migration will backfill both the new route and filename-derived ground truth for existing
records. Chat model activity will remain process-wide and authoritative; logout will ask
for eviction but will never forge an idle state, and the counter leak will be repaired at
the stream lifecycle boundary. Frontend metric types stay handwritten, guarded by a
schema assertion and a typed fixture rather than code generation.

**Tech stack:** Python 3.10, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, pytest,
React, TypeScript, OpenAPI, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-03-accuracy-metrics-review-remediation.md`

## Global constraints

- Compare against `origin/main` at `01f1cbc86053cac49cd889038e386a3321179a43`.
- Keep comments to one or two lines explaining an invariant or non-obvious reason.
- Domain/value objects use `BaseEntity`; services use plain constructors.
- Keep `DocumentCategory` and `ReviewRoute` typed inside Python domain/service code.
- Never infer historical state from a field that the workflow later mutates.
- Do not treat the checked-in `data/classiflow.db` as migration verification.
- Do not stage, commit, push, or create a PR without a new explicit user authorization.

## Target data model

`classification_records` will have three distinct concepts:

| Field | Meaning | Mutable after initial classification |
|---|---|---|
| `label` | Current accepted/reviewed label | Yes |
| `original_label` | First machine prediction, preserved when corrected | Set once |
| `expected_label` | Weak filename-derived corpus label | Set once unless explicitly repaired |
| `review_route` | Current workflow route | Yes |
| `machine_review_route` | Route selected for the original machine prediction | No |

For historical rows, `machine_review_route` can be reconstructed as follows:

- `human_overridden = true` implies the record originally entered `human_review`, because
  the decision endpoint only accepts records currently in that route.
- Otherwise, copy the existing `review_route`.

## Task 1: Lock the corrected metric semantics with failing tests

**Files:**

- Modify: `tests/services/test_metrics_service.py`
- Modify: `tests/api/routes/test_classification.py`

- [x] Add a service test where a machine miss originally used `human_review`, was later
  resolved to `accept`, and still contributes to `wrong_caught` rather than
  `wrong_uncaught`.
- [x] Add a service test where a record contains `expected_label`, `human_overridden=true`,
  and `original_label`; assert that the current human label is truth and
  `original_label` is the prediction.
- [x] Add a service test where a record has `human_overridden=true`, `original_label=NULL`
  and a non-null `expected_label`; assert it is excluded from `labelled` and every rate.
  This currently passes wrongly -- the record is included and scored reviewer-vs-filename.
- [x] Add an endpoint test proving that submitting a human decision preserves the first
  machine route and first machine prediction.
- [x] Add a repeated-update test proving neither immutable historical field can be
  overwritten.
- [x] Run the focused tests and record the expected failures:

```bash
uv run pytest tests/services/test_metrics_service.py tests/api/routes/test_classification.py -v
```

**Suggested commit boundary:** tests describing immutable classification history.

## Task 2: Persist the original machine review route

**Files:**

- Modify: `src/classiflow/database/models.py`
- Modify: `src/classiflow/classification/domain/results.py`
- Modify: `src/classiflow/classification/coordinator.py`
- Modify: `src/classiflow/classification/nodes/routing.py`
- Modify: `src/classiflow/api/routes/classification/endpoints.py`
- Modify: `src/classiflow/api/routes/documents/schemas.py`
- Modify: `src/classiflow/frontend/src/api/documents.ts`
- Modify: repository fixtures/builders that construct `ClassificationRecord`

- [x] Add nullable `machine_review_route` to `ClassificationRecord`. The migration is
  created in Task 4; keeping it nullable allows safe rollout and honest representation of
  unrecoverable data.
- [x] Add `machine_review_route: ReviewRoute | None` to `RoutingInput`.
- [x] On initial classification, populate both `review_route` and
  `machine_review_route` from the machine-selected route.
- [x] In `RoutingNode`, set `machine_review_route` only when the stored record does not
  already have one. Never clear or replace it during human review.
- [x] In the human-decision endpoint, pass through the stored historical route while
  updating only the current route.
- [x] Expose the field through document-detail schemas only if it is useful for audit or
  debugging; otherwise keep it internal and remove the frontend-document change from this
  task.
- [x] Run focused routing and endpoint tests:

```bash
uv run pytest tests/classification/test_routing_node.py tests/api/routes/test_classification.py -v
```

**Suggested commit boundary:** persist immutable machine routing history.

## Task 3: Correct ground-truth precedence and safeguarded accuracy

**Files:**

- Modify: `src/classiflow/services/metrics/service.py`
- Modify: `src/classiflow/services/metrics/domain.py`
- Modify: `tests/services/test_metrics_service.py`

- [x] Change `_ground_truth()` precedence:
  1. If `human_overridden` and `original_label` are present, use the current human label.
  2. If `human_overridden` and `original_label` is missing, exclude the record entirely --
     the machine prediction is unrecoverable and `label` holds the reviewer's answer, so
     `expected_label` would only score a human against a filename. This is the current
     behaviour for all 13 historical corrections and is contaminating strict accuracy.
  3. Otherwise use `expected_label` when present.
  4. Otherwise exclude the record from scoring.
- [x] Make `_prediction()` return `original_label` for a usable human correction and the
  current label otherwise. It must never fall through to `label` for an overridden record.
- [x] Determine `caught_by_safety_net` from `machine_review_route`, never the mutable
  `review_route`.
- [x] Validate category and route strings as `DocumentCategory` and `ReviewRoute` at the
  service boundary. Decide explicitly how corrupt/unknown database values are surfaced;
  do not silently count them as valid categories.
- [x] Keep API serialization compatible with the existing camel-case response.
- [x] Run focused tests and confirm the Task 1 failures are now green:

```bash
uv run pytest tests/services/test_metrics_service.py tests/api/routes/test_classification.py -v
```

**Suggested commit boundary:** correct truth precedence and safety-net accounting.

## Task 4: Add a migration and verify upgrade behavior

**Files:**

- Add: `alembic/versions/0015_backfill_accuracy_history.py`
- Add or modify: migration tests under `tests/`
- Modify only if necessary: `docs/accuracy-metrics.md`

- [x] Create revision `0015` with `down_revision = "0014"`.
- [x] Add `classification_records.machine_review_route` as nullable.
- [x] Backfill `machine_review_route`:
  - `human_overridden = true` -> `human_review`.
  - otherwise -> the row's current `review_route`.
  - preserve any pre-existing non-null value if the migration is written to be rerunnable.
- [x] Join classification records to jobs by `job_id` and backfill `expected_label` only
  when it is null.
- [x] Encode the filename mapping inside the migration rather than importing application
  code, so future refactors cannot change old migration behavior.
- [x] Match filenames case-insensitively, apply longer prefixes before shorter prefixes,
  preserve explicit `otro` mappings, and leave unknown filenames null.
- [x] Make downgrade remove only `machine_review_route`; document that data backfills are
  not reversed because clearing previously null `expected_label` values cannot be done
  reliably after later writes.
- [x] Add an upgrade test starting from an `0013`-shaped fixture. Assert recognized,
  explicit-`otro`, unknown, pre-populated, and human-overridden cases.
- [x] Run migration tests against a temporary database, not `data/classiflow.db`:

```bash
uv run pytest tests -k "migration or accuracy" -v
```

**Suggested commit boundary:** backfill historical accuracy metadata.

## Task 5: Remove unsafe logout activity resets

**Files:**

- Modify: `src/classiflow/api/routes/auth/endpoints.py`
- Modify: `src/classiflow/knowledge/llm/llama.py`
- Modify: `tests/api/routes/test_auth_oauth.py`
- Modify: `tests/knowledge/test_llama.py`
- Modify if lifecycle cleanup is incomplete: `src/classiflow/api/routes/knowledge/endpoints.py`

- [x] Add a failing test with an active generation proving logout does not evict the
  shared chat model.
- [x] Add tests for normal completion, provider failure, and consumer cancellation;
  activity must increment once and decrement once in every path.
- [x] Remove `reset_active_generations()` and its logout call.
- [x] Keep `unload_chat_llm()` as a guarded eviction request: it must no-op while the real
  active count is non-zero.
- [x] Repair the leak at the stream boundary. `_stream_tokens()` runs in a daemon thread,
  so its `finally` does fire once llama.cpp's blocking loop ends -- but on a client
  disconnect that loop runs to completion, holding the counter for the full generation.
  Starlette's `StreamingResponse` does not `aclose()` its body iterator on disconnect.
  - [x] Wrap the SSE generator in `contextlib.aclosing` and close it in a response-level
    `finally` in `api/routes/knowledge/endpoints.py`.
  - [x] Add a `threading.Event` stop signal, checked between emitted tokens in
    `_stream_tokens()`, set when the consumer goes away.
  - [x] Do not use `request.is_disconnected()` alone (polling, observes the disconnect
    late) or a timestamp reaper (cannot distinguish stale from slow; recreates the
    live-eviction race).
- [x] Do not force the counter to zero or clamp away underflow. If underflow is possible,
  raise/log an invariant failure in tests and fix the double-finalization path.
- [x] Keep logout successful even when model eviction is deferred.
- [x] Run focused concurrency tests repeatedly:

```bash
uv run pytest tests/knowledge/test_llama.py tests/api/routes/test_auth_oauth.py -v
```

**Suggested commit boundary:** make logout model eviction concurrency-safe.

## Task 6: Guard the metrics contract without code generation

**Files:**

- Add: backend OpenAPI schema test in `tests/api/routes/test_classification.py`
- Add: `src/classiflow/frontend/src/api/metrics.fixture.ts`
- Add: frontend contract test

Code generation is deferred: one endpoint does not justify a generator, a lockfile change
and a staleness check. The residual risk is named rather than eliminated -- these two tests
catch a rename on either side, but not a coordinated drift on both.

- [x] Add a backend test asserting the `/classification/metrics` OpenAPI schema: field
  names, required set, and camelCase aliases.
- [x] Add a fixture built from a real API response, typed `satisfies AccuracyReport`, so a
  renamed or removed field fails `tsc`.
- [x] Keep the handwritten `AccuracyReport` interface as the single frontend transport type.
- [x] Revisit generation only if the metrics API surface grows beyond this endpoint.
- [x] Run:

```bash
cd src/classiflow/frontend
npm run build
npm run test -- --run
```

**Suggested commit boundary:** guard the metrics contract with schema and fixture tests.

## Task 7: Simplify comments and clarify metrics UI names

**Files:**

- Modify: `src/classiflow/classification/ground_truth.py`
- Modify: `src/classiflow/services/metrics/domain.py`
- Modify: `src/classiflow/services/metrics/service.py`
- Modify: `src/classiflow/scripts/accuracy.py`
- Modify: `src/classiflow/knowledge/llm/llama.py`
- Modify: `src/classiflow/api/routes/classification/endpoints.py`
- Modify: `src/classiflow/classification/coordinator.py`
- Modify: `src/classiflow/classification/nodes/routing.py`
- Modify: `src/classiflow/database/models.py`
- Modify: `src/classiflow/frontend/src/pages/MetricsPage.tsx`
- Modify: affected tests containing long implementation narratives

- [x] Reduce implementation-history comments to one- or two-line invariants.
- [x] Keep extended discussion of weak labels, safety-net meaning, and metric caveats in
  `docs/accuracy-metrics.md`.
- [x] Rename `c`, `e`, and `p` callbacks/loop variables in confusion-matrix code to
  `category`, `expected`, and `predicted`.
- [x] Do not suppress lint rules to avoid the cleanup.
- [x] Run lint and focused frontend checks.

**Suggested commit boundary:** align accuracy code with comment and naming conventions.

## Task 8: Reproduce and document the corrected report

**Files:**

- Modify: `docs/accuracy-metrics.md`
- Generated output: `storage/reports/accuracy_*.md` according to repository policy

- [ ] Run all migrations against a copy of an `0013` database and verify the backfilled
  totals before using the current development database.
- [ ] Run `uv run poe accuracy` and compare CLI output with
  `GET /classification/metrics` from the same database.
- [ ] Confirm the Metrics page shows the same totals, per-category values, confusion
  matrix, and miss classifications.
- [ ] Update the point-in-time document only if the corrected semantics change its
  numbers. Explain changes without preserving obsolete figures as if still current.
- [ ] Do not commit incidental database mutations or timestamped reports unless they are
  intentional project artifacts.

**Suggested commit boundary:** refresh accuracy evidence and documentation.

## Final verification

- [ ] Review `git diff origin/main...HEAD` for unrelated logout/UI/database artifacts and
  split them where practical.
- [ ] Confirm every new migration has upgrade and downgrade coverage.
- [ ] Confirm the checked-in database is not the only place where historical labels exist.
- [ ] Run the complete backend gate:

```bash
uv run poe lint
uv run poe typecheck
uv run poe test
```

- [ ] Run the complete frontend gate:

```bash
cd src/classiflow/frontend
npm run build
npm run test -- --run
```

- [ ] Manually exercise two simultaneous authenticated sessions: start streaming in one,
  sign out in the other, and confirm the stream finishes without model eviction.
- [ ] Verify the final diff contains no accidental `data/classiflow.db`, generated report,
  frontend build output, or cache changes.

## Recommended execution order

```text
Task 1 tests
  -> Tasks 2-3 persistence and metric semantics
  -> Task 4 migration/backfill
  -> Task 5 concurrency repair
  -> Task 6 API contract guards
  -> Task 7 cleanup
  -> Task 8 evidence refresh
  -> final verification
```

Tasks 5 and 6 are independent after Task 1 and may be implemented in separate worktrees.
Tasks 2 through 4 must remain sequential because they evolve one database contract.

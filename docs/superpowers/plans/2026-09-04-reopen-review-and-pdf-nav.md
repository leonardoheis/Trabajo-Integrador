# Reopen a Review Decision · PDF First/Last — Implementation Plan

> **For implementers:** Work task-by-task and keep the checkboxes current. Write the
> regression test first for each behavioural change. Suggested commit boundaries are
> documented, but no commit, push, or PR is authorized by this plan.

**Goal:** Let an administrator return a mistakenly-decided document to the review queue,
with an attributable reason; and add first/last page controls to the PDF viewer.

**Architecture:** Reopening reuses `RoutingNode` — routing a record with
`review_route = human_review` already moves its file back to `review/human_review/`, so no
new file handling is needed. The endpoint is gated by the existing `require_admin`
dependency. The viewer change is local to `PdfViewer`.

**Tech stack:** Python 3.10, FastAPI, pytest, React, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-04-reopen-review-and-pdf-nav.md`

## Global constraints

- `label` is never reverted by a reopen (spec R2) — the operation must behave identically
  whether or not `original_label` exists.
- `machine_review_route` and `original_label` are history: a reopen must not touch them.
- Keep comments to one or two lines explaining an invariant or non-obvious reason.
- No `Any`, no `# noqa`, no `from __future__ import annotations`.
- Do not stage, commit, push, or create a PR without new explicit user authorization.
- Run `uv run poe check` after each task.

## Task 1: Lock the reopen contract with failing tests

**Files:**

- Modify: `tests/api/routes/test_classification.py`

Existing helpers to reuse: `_seed_human_review_job`, `_seed_classified_job`,
`auth_headers`, and the admin fixture pattern from `tests/api/routes/test_users.py`
(`_ADMIN_EMAIL` is already seeded in `tests/api/conftest.py`).

- [x] Non-admin reopen returns 403 and leaves `review_route` at `accept`.
- [x] Admin reopen of an `accept` record sets `review_route` to `human_review` and leaves
  `label` unchanged.
- [x] Reopen of a record already in `human_review` returns 409.
- [x] Reopen with `reason=""` or whitespace returns 422.
- [x] `machine_review_route` and `original_label` are byte-identical before and after.
- [x] A record with `original_label=None` (the legacy case) reopens the same way.
- [x] Reopen → decide again succeeds, and `original_label` is preserved from the first
  decision.

```bash
uv run pytest tests/api/routes/test_classification.py -v
```

**Suggested commit boundary:** tests describing the reopen contract.

## Task 2: Add the reopen endpoint

**Files:**

- Modify: `src/classiflow/api/routes/classification/endpoints.py`
- Modify: `src/classiflow/api/routes/classification/schemas.py`
- Modify: `src/classiflow/classification/exceptions.py`

- [x] Add `ClassificationReopenRequest` with a `reason: str` field. Validate non-empty
  after trimming — a Pydantic `field_validator` or `min_length` on the trimmed value, not
  a manual check in the endpoint.
- [x] Add `ClassificationNotDecidedError` (or reuse `ClassificationNotInReviewError`
  inverted) for the "not currently accepted" case, following the existing
  `@dataclass` exception style in that module.
- [x] Add `POST /classification/{job_id}/reopen` with
  `dependencies=[Depends(require_admin)]`. Note the router already applies
  `get_current_user` at router level, so only the admin check is added per-route.
- [x] Guard: 409 unless `record.review_route == ReviewRoute.ACCEPT`.
- [x] Write the audit record **before** the state change, carrying acting admin email,
  reason, and the label at reopen time.
- [x] Build a `RoutingInput` mirroring the decision endpoint's, but with
  `review_route=ReviewRoute.HUMAN_REVIEW` and `label=record.label` (unchanged). Pass
  `original_label` and `machine_review_route` straight through so `RoutingNode`'s
  write-once guards leave them alone.
- [x] Register the error handler if a new exception type was added.

```bash
uv run pytest tests/api/routes/test_classification.py -v
```

**Suggested commit boundary:** admin can reopen a review decision.

## Task 3: Frontend — reopen control

**Files:**

- Modify: `src/classiflow/frontend/src/api/classification.ts`
- Modify: `src/classiflow/frontend/src/pages/DocumentDetailPage.tsx`
- Add: a test alongside the existing page tests

- [x] Add `reopenClassification(jobId, reason)` to the API client, following
  `submitClassificationDecision`'s shape.
- [x] Render a **Reopen review** control on the Classification tab, visible only when
  `isAdmin && classification.reviewRoute === "accept" && classification.humanOverridden`.
  `useAuth()` already exposes `isAdmin`.
- [x] Require a reason before sending — a small inline input or a prompt, consistent with
  how `ReclassifyPanel` collects its notes.
- [x] On success, invalidate the `job-detail` and `review-queue` queries so both views
  reflect the change.
- [x] Surface failures rather than swallowing them: a 403 or 409 must be visible to the
  user.
- [x] Test: the control is absent for a non-admin, and absent for a record that was never
  human-overridden.

```bash
cd src/classiflow/frontend && npx vitest run && npx tsc -b
```

**Suggested commit boundary:** reopen control on the document detail page.

## Task 4: PDF first/last page controls

**Files:**

- Modify: `src/classiflow/frontend/src/components/PdfViewer.tsx`

The existing controls are at lines ~98-115: Prev at 100, the `Page n / m` label at 107,
Next at 110. `numPages` and `pageNumber` are already state.

- [x] Add `« First` before Prev and `Last »` after Next.
- [x] Render the pair only when `numPages > 1`.
- [x] `First` disabled when `pageNumber <= 1`; `Last` disabled when
  `pageNumber >= numPages` — mirroring Prev/Next.
- [x] Match the existing button styling exactly; no new visual vocabulary.
- [x] Test: both hidden for a single-page document, and each disabled at its boundary.

```bash
cd src/classiflow/frontend && npx vitest run && npm run build
```

**Suggested commit boundary:** first/last page controls in the PDF viewer.

## Task 5: Verify end to end

- [ ] Sign in as a non-admin: the Reopen control is not rendered, and a direct POST
  returns 403.
- [ ] Sign in as admin and reopen `convenio_394_2023.pdf` — the record that prompted this.
  Confirm it returns to the Review Queue and its file moves to `review/human_review/`.
- [ ] Re-decide it as `convenios` and confirm it files under `classified/convenios/`.
- [ ] Check the audit log shows the reopen with its reason.
- [ ] Open a 17-page document and confirm First/Last jump correctly and disable at the
  edges; open a single-page document and confirm neither control appears.
- [ ] Re-run `uv run poe accuracy` and note whether the corrected record changes the
  figures — it will not, since `original_label` is NULL, but confirm rather than assume.

**Suggested commit boundary:** none — verification only.

## Final verification

```bash
uv run poe lint
uv run poe typecheck
uv run poe test
cd src/classiflow/frontend
npm run build
npm run test -- --run
```

- [ ] Review `git diff` for unrelated changes.
- [ ] Confirm no `data/classiflow.db`, generated report, or build output churn beyond what
  is intended.

## Recommended execution order

```text
Task 1 tests
  -> Task 2 endpoint
  -> Task 3 frontend control
  -> Task 5 verification (reopen half)

Task 4 PDF controls  (independent — any time)
```

Task 4 shares nothing with Tasks 1-3 and can be done first if a quick win is wanted.

## Open questions for the implementer

1. **Where does the reason surface in the UI?** The audit tab already renders audit
   records; confirm the reopen record's `detail` renders legibly there rather than as raw
   JSON.
2. **Should a reopened record show a badge on the review queue** distinguishing it from a
   first-time review? Not required by the spec; decide when the queue is next touched.

# Reopen a Review Decision · PDF First/Last Page Controls

**Date:** 2026-09-04

## Context

Two unrelated gaps, grouped because both are small and both surfaced from the same screen.

### A human review decision is irreversible

`POST /classification/{job_id}/decision` sets `review_route = accept`, and the endpoint
then refuses any further decision with a 409 (`ClassificationNotInReviewError`). A reviewer
who picks the wrong label has no way to undo it: the document is filed under
`classified/<wrong label>/`, disappears from the Review Queue, and its wrong label is what
the Knowledge Base indexes.

The screenshot that prompted this is a real instance. `convenio_394_2023.pdf` — header
"REGISTRO DE CONVENIOS", `all_scores: {convenios: 1}`, SVM's only positive margin
`decreto: 0.58` — was corrected to `ordenanzas` and is now permanently filed there.

Two aggravating factors:

- The record shows `MACHINE ROUTE: HUMAN_REVIEW`, so the safety net *did* work. The error
  was introduced by the correction, not by the classifier.
- `original_label` is empty (the record predates that column), so this correction is also
  invisible to the accuracy metrics.

### PDF navigation has no jump-to-end

The viewer offers only Prev/Next. On a 17-page document, reaching the signatures page —
which is where a reviewer confirms the issuing body — takes 16 clicks.

## Goals

1. An administrator can return a mistakenly-decided document to the review queue.
2. Every reopen is attributable: who, when, and why.
3. Non-administrators cannot reopen.
4. Jumping to the first or last page of a multi-page PDF is one click.

## Non-goals

- Changing who may make a *review decision* — that stays open to any authenticated user.
- Editing a label directly without going through the review queue.
- Un-indexing from the Knowledge Base. A reopened document keeps whatever KB state it has;
  re-indexing after the corrected decision is existing behaviour.
- Reverting the label to the machine's prediction (see R2 — deliberately rejected).
- Page thumbnails, search, or any other viewer feature.

## Requirements

### R1. Admin-only reopen endpoint

`POST /classification/{job_id}/reopen`, gated by the existing `require_admin` dependency
(the same one protecting `/users` and `/audit`).

- A non-admin receives 403.
- A record not currently in `accept` receives 409 — reopening only applies to a decided
  document.
- The request body carries a **required** reason (non-empty, trimmed). A reopen without a
  stated cause is not permitted.

### R2. What reopening changes, and what it does not

| Field | After reopen |
|---|---|
| `review_route` | `human_review` |
| `label` | **unchanged** |
| `original_label` | unchanged |
| `machine_review_route` | unchanged — it is history |
| `human_overridden` | unchanged |
| `stored_path` | moved back to `review/human_review/` |

**`label` is deliberately not reverted.** Reverting to `original_label` would be
impossible for records predating that column — including the one that prompted this — and
would make the operation behave differently depending on when the record was created. The
reviewer re-deciding sees the current label as the starting point and the document itself
as the evidence.

The file move is `RoutingNode`'s existing behaviour: routing with
`review_route = human_review` already relocates to `review/human_review`. No new
file-handling logic.

### R3. Reopening is attributable

An audit record is written before the state change, carrying:

- the acting administrator's email
- the reason text
- the label at the time of reopening

The reason must survive in the audit log even if the record is later re-decided.

### R4. The reopened item behaves like any other review item

- It reappears in `GET /classification/review-queue`.
- A subsequent `POST /decision` on it succeeds — the 409 no longer applies, because the
  route is `human_review` again.
- Re-deciding preserves `original_label` if already set, per existing behaviour.

### R5. Reopen is discoverable only to administrators

The document detail page shows a **Reopen review** control on the Classification tab, and
only when:

- the current user is an administrator, **and**
- `reviewRoute === "accept"` and `humanOverridden === true` — i.e. this was a human
  decision that can meaningfully be contested.

Activating it requires entering a reason before the request is sent.

### R6. PDF first/last page controls

`PdfViewer` gains **First** and **Last** controls beside Prev/Next.

- Rendered only when the document has more than one page.
- `First` is disabled on page 1; `Last` is disabled on the final page — matching how
  Prev/Next already behave.
- No change to the existing zoom or fit-width controls.

## Acceptance criteria

- A non-admin calling the reopen endpoint receives 403 and the record is untouched.
- An admin reopening an `accept` record moves it to `human_review`, leaves `label`
  unchanged, and relocates the file to `review/human_review/`.
- Reopening a record that is already in `human_review` receives 409.
- A reopen with an empty or whitespace-only reason is rejected.
- The audit log contains the acting admin, the reason, and the prior label.
- A reopened record appears in the review queue and can be decided again.
- `machine_review_route` and `original_label` are identical before and after a reopen.
- The First/Last controls are absent on a single-page document and correctly disabled at
  the boundaries.
- Ruff, strict mypy, backend tests, frontend tests and the production build all pass.

## Required regression tests

1. Non-admin reopen → 403, record unchanged.
2. Admin reopen of an `accept` record → `human_review`, `label` unchanged, file moved.
3. Reopen of a record already in `human_review` → 409.
4. Reopen with a blank reason → 422.
5. Audit record contains admin email, reason and prior label.
6. Reopen → decide again → succeeds, and `original_label` is preserved.
7. A reopened record whose `original_label` is NULL (the legacy case) behaves identically.
8. Frontend: the control is hidden for non-admins and for records that were never
   human-overridden.
9. Frontend: First/Last hidden on a one-page document; disabled at the respective edges.

## Validation commands

```bash
uv run poe lint
uv run poe typecheck
uv run poe test
cd src/classiflow/frontend
npm run build
npm run test -- --run
```

## Notes

- **This does not repair the existing mistake.** `convenio_394_2023.pdf` must be reopened
  and re-decided through the new endpoint once it ships. Its `original_label` will stay
  NULL, so it remains excluded from accuracy metrics either way.
- **Metrics impact.** A reopened record leaves `accept` and so drops out of the
  auto-accepted count until re-decided. That is correct: it is genuinely back under review.
- The two features share nothing but this document. They can ship as separate commits and
  either can be dropped without affecting the other.

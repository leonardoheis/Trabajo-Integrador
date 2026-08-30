# "Indexed" Column on the Classification Table — Design Spec

## Status

Draft — pending user review.

## Context

The Classification page's document table (`ClassificationPage.tsx`) has no visibility into whether
a document has been indexed into the Knowledge Base. A document only reaches `document_kb` after
an explicit action — the per-document "Index into Knowledge Base" button on Document Detail, or the
batch "Sync Knowledge Base" action on this same page — so today the only way to know whether a
given row was actually indexed is to open its Document Detail page and check the Knowledge Base
tab. This spec adds a column to the table itself.

`GET /jobs` (`list_completed_jobs` in `src/classiflow/api/routes/documents/endpoints.py:56-98`)
already builds each row with a per-job lookup inside a loop — `classification_repo.find_by_job_id`
— to fill in label/review route/confidence. `IDocumentKbRepository.find_by_job_id` already exists
(added for the Document Detail KB tab). Adding one more per-job lookup of the same shape is the
entire backend change.

## Decisions

### 1. Boolean, not a tri-state

The column reflects only whether a `DocumentKb` row exists for the job — `indexed: bool`. It does
not distinguish "rejected, can never be indexed" from "accepted, not indexed yet": the existing
Review Route column sitting next to it already carries that distinction (`reject` / `human_review`
/ `accept`), so a document showing `Indexed: No` next to `Review Route: reject` is unambiguous
without the indexed value itself needing a third state. Introducing a second enum here would
duplicate what Review Route already encodes.

### 2. Field name: `indexed`, matching existing terminology

Named `indexed` (not `embedded`) to match every other user-facing and code-level name for this
concept already in the app: the `DocumentKb` model, `indexed_at`, `IndexerService`,
`index_enriched_record`/`synchronize_kb`, the Document Detail page's "Index into Knowledge Base"
button and its "Not indexed yet" empty state. "Embedded" is accurate to the underlying mechanism
but would be a second word for the same idea inside one UI.

### 3. Column: plain text Yes/No, not a badge

Renders as `Yes`/`No`, matching the existing "Judged" column's style
(`ClassificationPage.tsx:32`), not a colored `StatusBadge` like Review Route. Review Route earns a
badge because it's a multi-value enum where color usefully distinguishes states; a boolean sitting
next to another boolean column doesn't need one.

### 4. Backend: one more per-job lookup, same shape as the existing one

**File:** `src/classiflow/api/routes/documents/endpoints.py`

`list_completed_jobs` gains a `document_kb_repo` param:

```python
document_kb_repo: Annotated[IDocumentKbRepository, Depends(get_document_kb_repo)],
```

Inside the existing per-job loop, alongside the existing `classification_repo.find_by_job_id`
call:

```python
doc_kb = await document_kb_repo.find_by_job_id(job.job_id)
...
summaries.append(
    ClassificationSummary(
        ...,  # unchanged existing fields
        indexed=doc_kb is not None,
    )
)
```

**File:** `src/classiflow/api/routes/documents/schemas.py`

`ClassificationSummary` gains `indexed: bool`.

### 5. Frontend: one field, one column

**File:** `src/classiflow/frontend/src/api/documents.ts` — `ClassificationSummary` interface gains
`indexed: boolean`.

**File:** `src/classiflow/frontend/src/pages/ClassificationPage.tsx` — `COLUMNS` gains, placed
immediately after "Judged" (both are simple derived booleans, read as a pair):

```tsx
{ header: "Indexed", render: (row) => (row.indexed ? "Yes" : "No") },
```

## Non-Goals

- **No sort support** for the new column — matches "Judged" and "Review Route," neither of which
  is sortable today.
- **No filter control** for indexed/not-indexed — there's no filter UI for `reviewRoute` either
  despite the backend already accepting that query param; adding one for `indexed` alone would be
  new surface area nothing asked for.
- **No change to how indexing itself is triggered** — the per-document button and the batch sync
  action are unchanged. This column is read-only visibility, not a new indexing trigger.

## Testing

- **Backend:** extend `tests/api/routes/test_documents.py`'s `TestJobsListEndpoint` — seed two jobs
  via the existing `_seed_classified_job` helper, save a `DocumentKb` row for one via
  `test_container.document_kb_repo().save(...)`, assert `indexed: true` / `indexed: false` on the
  corresponding response items.
- **Frontend:** no new test. No page-level `.test.tsx` exists for any page component in this
  codebase (component tests exist only for pieces with real branching logic — `StepTimeline`,
  `ReclassifyPanel`); this column is exactly as trivial as the untested "Judged" column beside it.
- Run `uv run poe check` per the project's standard gate — hand to the user rather than running
  directly.

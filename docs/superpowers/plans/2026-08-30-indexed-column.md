# "Indexed" Column Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Indexed" column to the Classification page's document table, showing Yes/No for
whether each document has been indexed into the Knowledge Base.

**Architecture:** One backend field (`ClassificationSummary.indexed: bool`), populated in
`list_completed_jobs` by the same per-job-lookup pattern the function already uses for
classification data — a `document_kb_repo.find_by_job_id(job.job_id)` call, existence check.
One frontend field and one table column, following existing `ClassificationSummary`/`COLUMNS`
conventions exactly.

**Tech Stack:** FastAPI, Pydantic (backend); React 19, TypeScript (frontend); pytest (backend
tests).

**Spec:** `docs/superpowers/specs/2026-08-30-indexed-column-design.md`

## Global Constraints

- Boolean only — no tri-state, no new enum (spec Decision 1).
- Field/column name is `indexed`, not `embedded` (spec Decision 2).
- Plain text `Yes`/`No`, no colored badge (spec Decision 3).
- Not sortable, not filterable (spec Non-Goals).
- No new frontend test — no page-level `.test.tsx` exists in this codebase today, and this column
  is exactly as trivial as the untested "Judged" column beside it (spec Testing section).

---

### Task 1: Backend — `indexed` field on `ClassificationSummary`

**Files:**
- Modify: `src/classiflow/api/routes/documents/schemas.py`
- Modify: `src/classiflow/api/routes/documents/endpoints.py`
- Modify: `tests/api/routes/test_documents.py`

**Interfaces:**
- Consumes: `IDocumentKbRepository.find_by_job_id(job_id: str) -> DocumentKb | None` (already
  exists, `src/classiflow/domain/repositories/document_kb.py`); `get_document_kb_repo` dependency
  (already exists, `src/classiflow/api/dependencies.py:139`); `TestContainer.document_kb_repo()`
  (already exists, `src/classiflow/injections/test.py:164`).
- Produces: `ClassificationSummary.indexed: bool`, consumed by Task 2's frontend interface.

- [ ] **Step 1: Write the failing test**

In `tests/api/routes/test_documents.py`, add to `TestJobsListEndpoint`:

```python
from classiflow.database.models import DocumentKb


async def test_marks_indexed_documents(
    self,
    client: TestClient,
    auth_headers: dict[str, str],
    test_container: TestContainer,
) -> None:
    await _seed_classified_job(test_container, "job-indexed-1", "indexed-me.pdf")
    await _seed_classified_job(test_container, "job-not-indexed-1", "not-indexed-me.pdf")
    await test_container.document_kb_repo().save(
        DocumentKb(
            job_id="job-indexed-1",
            sha256="a" * 64,
            filename="indexed-me.pdf",
            chunk_count=3,
        )
    )

    response = client.get("/jobs", headers=auth_headers)

    assert response.status_code == HTTPStatus.OK
    items = {i["filename"]: i for i in response.json()["items"]}
    assert items["indexed-me.pdf"]["indexed"] is True
    assert items["not-indexed-me.pdf"]["indexed"] is False
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `uv run pytest tests/api/routes/test_documents.py -k marks_indexed_documents -v`
Expected: FAIL — `ClassificationSummary` has no `indexed` field yet, so the response won't have
that key (`KeyError` on `items["indexed-me.pdf"]["indexed"]`).

- [ ] **Step 3: Add the field to the schema**

In `src/classiflow/api/routes/documents/schemas.py`, add to `ClassificationSummary`:

```python
class ClassificationSummary(BaseSchema):
    job_id: str
    filename: str
    status: str
    label: str | None
    review_route: str
    confidence: float
    judged_by_llm: bool
    created_at: datetime
    indexed: bool
```

- [ ] **Step 4: Populate it in the endpoint**

In `src/classiflow/api/routes/documents/endpoints.py`, add the import and dependency param:

```python
from classiflow.api.dependencies import (
    get_audit_repo,
    get_classification_record_repo,
    get_current_user,
    get_document_kb_repo,
    get_enriched_record_repo,
    get_job_repo,
)
from classiflow.domain.repositories.document_kb import IDocumentKbRepository
```

```python
@router.get("/jobs")
async def list_completed_jobs(
    job_repo: Annotated[IJobRepository, Depends(get_job_repo)],
    classification_repo: Annotated[
        IClassificationRecordRepository, Depends(get_classification_record_repo)
    ],
    document_kb_repo: Annotated[IDocumentKbRepository, Depends(get_document_kb_repo)],
    label: str | None = None,
    review_route: Annotated[str | None, Query(alias="reviewRoute")] = None,
    page: int = 1,
    page_size: Annotated[int, Query(alias="pageSize")] = 25,
    sort: SortField | None = None,
    sort_dir: Annotated[Literal["asc", "desc"], Query(alias="sortDir")] = "asc",
) -> JobsPage:
    all_jobs = await job_repo.list_all()
    completed = [j for j in all_jobs if j.status not in {"queued", "processing"}]

    summaries = []
    for job in completed:
        record = await classification_repo.find_by_job_id(job.job_id)
        if label is not None and (record is None or record.label != label):
            continue
        if review_route is not None and (record is None or record.review_route != review_route):
            continue
        doc_kb = await document_kb_repo.find_by_job_id(job.job_id)
        summaries.append(
            ClassificationSummary(
                job_id=job.job_id,
                filename=job.filename,
                status=job.status,
                label=record.label if record else None,
                review_route=record.review_route if record else "n/a",
                confidence=record.confidence if record else 0.0,
                judged_by_llm=record.judged_by_llm if record else False,
                created_at=job.created_at,
                indexed=doc_kb is not None,
            )
        )
    ...  # rest of the function unchanged
```

- [ ] **Step 5: Run the test, confirm it passes**

Run: `uv run pytest tests/api/routes/test_documents.py -k marks_indexed_documents -v`
Expected: PASS

- [ ] **Step 6: Run the full endpoint test file to confirm no regression**

Run: `uv run pytest tests/api/routes/test_documents.py -v`

- [ ] **Step 7: Commit**

```bash
git add src/classiflow/api/routes/documents/schemas.py src/classiflow/api/routes/documents/endpoints.py tests/api/routes/test_documents.py
git commit -m "feat: add indexed field to the jobs list endpoint"
```

---

### Task 2: Frontend — "Indexed" column

**Files:**
- Modify: `src/classiflow/frontend/src/api/documents.ts`
- Modify: `src/classiflow/frontend/src/pages/ClassificationPage.tsx`

**Interfaces:**
- Consumes: `ClassificationSummary.indexed: boolean` (Task 1's backend field, camelCase per
  `BaseSchema`'s alias generator — no separate frontend mapping step needed).

- [ ] **Step 1: Add the field to the TypeScript interface**

In `src/classiflow/frontend/src/api/documents.ts`, add to `ClassificationSummary`:

```ts
export interface ClassificationSummary {
  jobId: string;
  filename: string;
  status: string;
  label: string | null;
  reviewRoute: string;
  confidence: number;
  judgedByLlm: boolean;
  createdAt: string;
  indexed: boolean;
}
```

- [ ] **Step 2: Add the column**

In `src/classiflow/frontend/src/pages/ClassificationPage.tsx`, add to `COLUMNS`, immediately after
the "Judged" entry:

```tsx
const COLUMNS: Column<ClassificationSummary>[] = [
  { header: "Filename", sortKey: "filename", render: (row) => row.filename },
  { header: "Label", sortKey: "label", render: (row) => row.label ?? "—" },
  {
    header: "Review Route",
    render: (row) => (
      <StatusBadge status={row.reviewRoute === "n/a" ? row.status : row.reviewRoute} />
    ),
  },
  {
    header: "Confidence",
    sortKey: "confidence",
    render: (row) =>
      row.reviewRoute === "n/a" ? (
        <span className="font-mono text-[var(--color-text-faint)]">—</span>
      ) : (
        <span className="font-mono text-[var(--color-text-muted)]">
          {row.confidence.toFixed(2)}
        </span>
      ),
  },
  { header: "Judged", render: (row) => (row.judgedByLlm ? "Yes" : "No") },
  { header: "Indexed", render: (row) => (row.indexed ? "Yes" : "No") },
  {
    header: "Created",
    sortKey: "createdAt",
    render: (row) => (
      <span className="font-mono text-xs text-[var(--color-text-faint)]">
        {new Date(row.createdAt).toLocaleString()}
      </span>
    ),
  },
];
```

- [ ] **Step 3: Verify with the typechecker and linter**

Run: `uv run poe lint` (this repo's `poe check` runs frontend ESLint/Prettier and `tsc` as part of
pre-commit; running the lint step alone here is enough to catch a type mismatch on the new field
without waiting for the full suite).

No automated frontend test is added for this step, per the spec's Testing section — matches the
existing untested "Judged" column.

- [ ] **Step 4: Commit**

```bash
git add src/classiflow/frontend/src/api/documents.ts src/classiflow/frontend/src/pages/ClassificationPage.tsx
git commit -m "feat: show an Indexed column on the Classification page"
```

---

### Task 3: Whole-app verification

- [ ] Run `uv run poe check` (lint + typecheck + full backend test suite) — hand to the user per
  this repo's execution-workflow rule.
- [ ] Manual check (hand to the user, `uv run poe serve` running): open the Classification page,
  confirm the "Indexed" column shows "Yes" for a document already indexed via the "Index into
  Knowledge Base" button or "Sync Knowledge Base", and "No" for one that isn't.

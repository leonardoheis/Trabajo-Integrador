# Frontend Knowledge Base Integration Implementation Plan

**Status: done (Tasks 1–6 code + verification complete; Task 7's manual browser walkthrough
still pending — hand to the user with both servers running).**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the already-built Stage 5 Knowledge Base / RAG backend into the frontend: a
"Knowledge Base" tab on Document Detail showing a document's indexing record, a "Sync Knowledge
Base" button on the Classification page that triggers the existing batch reindex endpoint, and a
working streaming Chat page replacing the current stub.

**Architecture:** One small backend addition (a `GET /knowledge/documents/{job_id}` read endpoint
and matching repository method — everything else on the backend, including `synchronize-kb` and
both chat endpoints, already exists and is already tested) plus a frontend wiring pass that
follows existing conventions exactly: `apiFetch` + TanStack Query for reads, `useMutation` for the
one-shot sync action, and a manual `fetch` + `ReadableStream` reader for the chat stream (the only
new *pattern* introduced, since no POST-based SSE consumption exists in this codebase yet — the
existing `EventSource` precedent only covers GET streams).

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic (backend); React 19, TypeScript, Vite 6,
TanStack Query, Tailwind v4 (frontend); pytest (backend tests), Vitest + Testing Library (frontend
tests, where added).

**Spec:** `docs/superpowers/specs/2026-08-26-frontend-knowledge-base-design.md`

## Global Constraints

- No changes to indexing/chunking/embedding/retrieval/LLM-provider internals, or to the existing
  `synchronize-kb`, `chat`, or `chat/stream` endpoints' behavior — only new code that reads
  existing data or calls existing endpoints.
- No new npm dependencies — the chat stream is consumed with the platform `fetch`/`ReadableStream`
  APIs, no SSE client library.
- No toast/notification system introduction — the sync button's result is a plain inline status
  string, matching this codebase's existing "no extra UI infrastructure" style.
- No per-document reindex action and no chat filter UI — both explicit Non-Goals in the spec.
- Follow `CLAUDE.md` exactly on new backend code: full type annotations, no `Any`, no
  `from __future__ import annotations`, no `TYPE_CHECKING` unless a real circular import forces
  it, `BaseSchema` (camelCase alias generator) for all new Pydantic schemas.

---

### Task 1: Backend — `find_by_job_id` on the document_kb repository

**Files:**
- Modify: `src/classiflow/domain/repositories/document_kb.py`
- Modify: `src/classiflow/database/repositories/document_kb.py`
- Modify: `tests/shared/test_repositories.py`

**Interfaces:**
- Consumes: `DocumentKb` (`src/classiflow/database/models.py`, unchanged).
- Produces: `find_by_job_id(job_id: str) -> DocumentKb | None` added to `IDocumentKbRepository`,
  `SqlDocumentKbRepository`, and `InMemoryDocumentKbRepository`. Consumed by Task 2's new route.

- [x] **Step 1: Write the failing tests**

In `tests/shared/test_repositories.py`, add to `TestSqlDocumentKbRepository`:

```python
async def test_find_by_job_id(self, session: AsyncSession) -> None:
    repo = SqlDocumentKbRepository(session)
    await repo.save(_document_kb())
    found = await repo.find_by_job_id(_JOB)
    assert found is not None
    assert found.sha256 == _SHA


async def test_find_by_job_id_missing_returns_none(self, session: AsyncSession) -> None:
    repo = SqlDocumentKbRepository(session)
    assert await repo.find_by_job_id("no-such-job") is None
```

And to `TestInMemoryDocumentKbRepository`:

```python
async def test_find_by_job_id(self) -> None:
    repo = InMemoryDocumentKbRepository()
    await repo.save(_document_kb())
    found = await repo.find_by_job_id(_JOB)
    assert found is not None
    assert found.sha256 == _SHA


async def test_find_by_job_id_missing_returns_none(self) -> None:
    repo = InMemoryDocumentKbRepository()
    assert await repo.find_by_job_id("no-such-job") is None
```

- [x] **Step 2: Run tests to verify they fail**

Ran `uv run pytest tests/shared/test_repositories.py -k find_by_job_id -v`: confirmed 4/4 FAIL
with `AttributeError` on both `SqlDocumentKbRepository` and `InMemoryDocumentKbRepository`.

- [x] **Step 3: Implement `find_by_job_id`**

In `src/classiflow/domain/repositories/document_kb.py`, add to the protocol:

```python
class IDocumentKbRepository(Protocol):
    async def save(self, document: DocumentKb) -> None: ...
    async def find_by_sha256(self, sha256: str) -> DocumentKb | None: ...
    async def find_by_job_id(self, job_id: str) -> DocumentKb | None: ...
    async def list_all(self) -> list[DocumentKb]: ...
```

In `src/classiflow/database/repositories/document_kb.py`, add to `SqlDocumentKbRepository`
(mirrors `find_by_sha256`'s shape):

```python
async def find_by_job_id(self, job_id: str) -> DocumentKb | None:
    result = await self._session.execute(select(DocumentKb).where(DocumentKb.job_id == job_id))
    return result.scalar_one_or_none()
```

And to `InMemoryDocumentKbRepository`:

```python
    async def find_by_job_id(self, job_id: str) -> DocumentKb | None:
        return next((doc for doc in self._store.values() if doc.job_id == job_id), None)
```

- [x] **Step 4: Run tests to verify they pass**

`uv run pytest tests/shared/test_repositories.py -k find_by_job_id -v`: **4/4 PASS**.

- [x] **Step 5: Run the full check**

Deferred to Task 7's whole-app check rather than run in isolation here — see Task 7.

- [ ] **Step 6: Commit** — skipped. This repo's git workflow requires explicit per-message user
  authorization before any `git commit`; not run.

---

### Task 2: Backend — `GET /knowledge/documents/{job_id}` endpoint

**Files:**
- Modify: `src/classiflow/api/routes/knowledge/schemas.py`
- Modify: `src/classiflow/api/routes/knowledge/endpoints.py`
- Modify: `tests/api/routes/test_knowledge.py`
- Modify: `tests/api/conftest.py` (found during execution — see Step 4)
- Modify: `src/classiflow/services/pipeline/service.py` (found during execution — see Step 4)

**Interfaces:**
- Consumes: `IDocumentKbRepository.find_by_job_id` (Task 1), `get_document_kb_repo`
  (`src/classiflow/api/dependencies.py`, already exists — no DI change needed), `get_current_user`
  (already applied at router level).
- Produces: `DocumentKbSchema`, `DocumentKbResponse` (new schemas) and
  `GET /knowledge/documents/{job_id} -> DocumentKbResponse`. Consumed by Task 3's frontend API
  client.

- [x] **Step 1: Write the failing tests**

In `tests/api/routes/test_knowledge.py`, add a new test class (reusing the module's existing
`_ingest` helper):

```python
class TestDocumentKbEndpoint:
    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get("/knowledge/documents/some-job")
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_returns_null_when_not_indexed(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/knowledge/documents/no-such-job", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        assert response.json()["documentKb"] is None

    def test_returns_the_kb_record_once_indexed(
        self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = _ingest(client, auth_headers, monkeypatch, filename="kb-detail.pdf")
        client.post("/knowledge/synchronize-kb", headers=auth_headers)

        response = client.get(f"/knowledge/documents/{job_id}", headers=auth_headers)
        assert response.status_code == HTTPStatus.OK
        body = response.json()["documentKb"]
        assert body is not None
        assert body["filename"] == "kb-detail.pdf"
        assert isinstance(body["chunkCount"], int)
```

- [x] **Step 2: Run tests to verify they fail**

Ran `uv run pytest tests/api/routes/test_knowledge.py -k DocumentKb -v`: confirmed 3/3 FAIL with
`404 Not Found` (no such route registered yet).

- [x] **Step 3: Implement the schema and route**

In `src/classiflow/api/routes/knowledge/schemas.py`, add:

```python
from datetime import datetime

from classiflow.database.models import DocumentKb


class DocumentKbSchema(BaseSchema):
    sha256: str
    filename: str
    doc_type: str | None
    number: str | None
    year: str | None
    subject: str | None
    sanction_date: str | None
    publication_date: str | None
    bulletin_number: str | None
    download_url: str | None
    chunk_count: int
    indexed_at: datetime

    @classmethod
    def from_model(cls, doc: DocumentKb) -> "DocumentKbSchema":
        return cls(
            sha256=doc.sha256,
            filename=doc.filename,
            doc_type=doc.doc_type,
            number=doc.number,
            year=doc.year,
            subject=doc.subject,
            sanction_date=doc.sanction_date,
            publication_date=doc.publication_date,
            bulletin_number=doc.bulletin_number,
            download_url=doc.download_url,
            chunk_count=doc.chunk_count,
            indexed_at=doc.indexed_at,
        )


class DocumentKbResponse(BaseSchema):
    document_kb: DocumentKbSchema | None
```

In `src/classiflow/api/routes/knowledge/endpoints.py`, add the import
(`get_document_kb_repo`, `DocumentKbResponse`, `DocumentKbSchema`, `IDocumentKbRepository`) and
the route:

```python
@router.get("/documents/{job_id}")
async def document_kb(
    job_id: str,
    document_kb_repo: Annotated[IDocumentKbRepository, Depends(get_document_kb_repo)],
) -> DocumentKbResponse:
    doc = await document_kb_repo.find_by_job_id(job_id)
    return DocumentKbResponse(document_kb=DocumentKbSchema.from_model(doc) if doc else None)
```

- [x] **Step 4: Run tests to verify they pass**

First run surfaced two unplanned gaps, both fixed before all 3 tests passed:

1. **`tests/api/conftest.py` had no override for `get_document_kb_repo`.** Unlike
   `get_job_repo`/`get_document_steps_repo`/etc., this dependency was never wired into the
   `client` fixture's `app.dependency_overrides`, so the test client resolved it against the
   real on-disk `data/classiflow.db` (which has no `document_kb` table applied) instead of
   `TestContainer`'s in-memory repo — surfaced as `sqlite3.OperationalError: no such table:
   document_kb`. Added the override, following the existing pattern exactly.

   Adding a 10th override pushed the `client` fixture's cyclomatic complexity over the
   linter's threshold (`C901: 11 > 10`) once `uv run poe check` ran. Rather than bump the
   config, collapsed the nine near-identical `_x_override()` closures (each just
   `return test_container.x()`) into one generic `_override(provider)` helper using a
   `TypeVar`, and rewrote the ten override registrations as one-liners calling it — a real
   simplification, not a lint workaround, and it let ruff auto-remove ~9 now-unused
   `I*Repository`/`PipelineService`/`JobService`/`IAuditRepository` imports.

2. **`indexed_at` was `None` on records saved through the in-memory repo.**
   `_build_document_kb()` in `services/pipeline/service.py` relied on
   `server_default=func.now()` to populate `DocumentKb.indexed_at`, but that only fires on a
   real SQL `INSERT` — `InMemoryDocumentKbRepository` never round-trips through SQL, matching
   an already-documented pattern elsewhere in this file (`Job.created_at`/`updated_at`).
   Fixed by setting `indexed_at=datetime.now(timezone.utc)` explicitly in
   `_build_document_kb`, the same fix `PipelineService.start()` already applies to `Job`.

After both fixes: `uv run pytest tests/api/routes/test_knowledge.py -k DocumentKb -v`: **3/3
PASS**.

- [x] **Step 5: Run the full check**

Deferred to Task 7's whole-app check — see Task 7.

- [ ] **Step 6: Commit** — skipped, same git-workflow reason as Task 1.

---

### Task 3: Frontend — `api/knowledge.ts` client module + Vite proxy

**Files:**
- Create: `src/classiflow/frontend/src/api/knowledge.ts`
- Modify: `src/classiflow/frontend/vite.config.ts`

**Interfaces:**
- Consumes: `apiFetch` from `./auth` (existing convention).
- Produces:
  ```typescript
  export interface DocumentKbRecord { ... }
  export interface DocumentKbResponse { documentKb: DocumentKbRecord | null }
  export async function fetchDocumentKb(jobId: string): Promise<DocumentKbResponse>;

  export interface SynchronizeKbResult { indexedJobIds: string[]; skippedCount: number }
  export async function synchronizeKb(): Promise<SynchronizeKbResult>;
  ```
  Consumed by Task 4 (`fetchDocumentKb`) and Task 5 (`synchronizeKb`). Chat's own streaming call
  is built directly in Task 6 (not through this module — see that task for why).

- [x] **Step 1: Add the `/knowledge` proxy entry**

In `src/classiflow/frontend/vite.config.ts`, add one line to `server.proxy` (plain target, not
`apiOnly()` — there is no frontend SPA route at `/knowledge`, so there's no page-load-vs-API-call
ambiguity for this prefix):

```ts
      "/knowledge": "http://127.0.0.1:8000",
```

- [x] **Step 2: Create the API client module**

Create `src/classiflow/frontend/src/api/knowledge.ts`:

```ts
import { apiFetch } from "./auth";

export interface DocumentKbRecord {
  sha256: string;
  filename: string;
  docType: string | null;
  number: string | null;
  year: string | null;
  subject: string | null;
  sanctionDate: string | null;
  publicationDate: string | null;
  bulletinNumber: string | null;
  downloadUrl: string | null;
  chunkCount: number;
  indexedAt: string;
}

export interface DocumentKbResponse {
  documentKb: DocumentKbRecord | null;
}

export async function fetchDocumentKb(jobId: string): Promise<DocumentKbResponse> {
  const response = await apiFetch(`/knowledge/documents/${jobId}`);
  if (!response.ok) {
    throw new Error(`GET /knowledge/documents/${jobId} failed: ${response.status}`);
  }
  return response.json();
}

export interface SynchronizeKbResult {
  indexedJobIds: string[];
  skippedCount: number;
}

export async function synchronizeKb(): Promise<SynchronizeKbResult> {
  const response = await apiFetch("/knowledge/synchronize-kb", { method: "POST" });
  if (!response.ok) {
    throw new Error(`POST /knowledge/synchronize-kb failed: ${response.status}`);
  }
  return response.json();
}
```

- [ ] **Step 3: Manual check** — not run (requires a live dev server); folded into Task 7's
  end-to-end walkthrough instead of a standalone check here.

- [x] **Step 4: Run typecheck and lint**

`npx tsc -b && npm run lint` (from `src/classiflow/frontend/`): both clean.

- [ ] **Step 5: Commit** — skipped, same git-workflow reason as Task 1.

---

### Task 4: Frontend — Knowledge Base tab on Document Detail

**Files:**
- Modify: `src/classiflow/frontend/src/pages/DocumentDetailPage.tsx`

**Interfaces:**
- Consumes: `fetchDocumentKb`, `DocumentKbResponse` from `../api/knowledge` (Task 3); the file's
  existing `KeyValueGrid` helper (unchanged).
- Produces: no new exports — same default export. `Tab` union gains `"knowledge"`.

- [x] **Step 1: Add the tab and a second query**

In `src/classiflow/frontend/src/pages/DocumentDetailPage.tsx`:

Add the import: `import { fetchDocumentKb } from "../api/knowledge";`

Update the tab union and list:

```ts
type Tab = "extraction" | "enrichment" | "classification" | "knowledge" | "audit";

const TABS: Tab[] = ["extraction", "enrichment", "classification", "knowledge", "audit"];
```

Add a second query alongside the existing `job-detail` one, inside the component body:

```ts
  const { data: kbData } = useQuery({
    queryKey: ["document-kb", jobId],
    queryFn: () => fetchDocumentKb(jobId!),
    enabled: !!jobId,
  });
```

- [x] **Step 2: Add the tab content block**

Add this block among the other `{tab === "..." && (...)}` blocks (placed after the
classification block, before the audit block, matching the tab order):

```tsx
        {tab === "knowledge" && kbData?.documentKb && (
          <KeyValueGrid
            pairs={[
              ["Filename", kbData.documentKb.filename],
              ["SHA-256", <span key="sha" className="font-mono text-xs">{kbData.documentKb.sha256}</span>],
              ["Doc type", kbData.documentKb.docType ?? "—"],
              ["Number", kbData.documentKb.number ?? "—"],
              ["Year", kbData.documentKb.year ?? "—"],
              ["Subject", kbData.documentKb.subject ?? "—"],
              ["Sanction date", kbData.documentKb.sanctionDate ?? "—"],
              ["Publication date", kbData.documentKb.publicationDate ?? "—"],
              ["Bulletin number", kbData.documentKb.bulletinNumber ?? "—"],
              ["Chunk count", String(kbData.documentKb.chunkCount)],
              ["Indexed at", new Date(kbData.documentKb.indexedAt).toLocaleString()],
              ...(kbData.documentKb.downloadUrl
                ? ([
                    [
                      "Download URL",
                      <a
                        key="url"
                        href={kbData.documentKb.downloadUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[var(--color-accent)] hover:underline"
                      >
                        {kbData.documentKb.downloadUrl}
                      </a>,
                    ],
                  ] as [string, React.ReactNode][])
                : []),
            ]}
          />
        )}
        {tab === "knowledge" && !kbData?.documentKb && (
          <p className="text-sm text-[var(--color-text-muted)]">Not indexed yet</p>
        )}
```

- [ ] **Step 3: Manual visual check** — not run; folded into Task 7's end-to-end walkthrough.

- [x] **Step 4: Run typecheck, lint, and tests**

`npx tsc -b && npm run lint && npm run test` (from `src/classiflow/frontend/`): all clean,
**20/20 tests passed** (no new tests added for this page — existing suite unaffected).

- [ ] **Step 5: Commit** — skipped, same git-workflow reason as Task 1.

---

### Task 5: Frontend — "Sync Knowledge Base" button on Classification page

**Files:**
- Modify: `src/classiflow/frontend/src/pages/ClassificationPage.tsx`

**Interfaces:**
- Consumes: `synchronizeKb`, `SynchronizeKbResult` from `../api/knowledge` (Task 3);
  `useMutation`, `useQueryClient` from `@tanstack/react-query` (new imports for this file — it
  currently only uses `useQuery`).
- Produces: no new exports — same default export.

- [x] **Step 1: Add the mutation and button**

In `src/classiflow/frontend/src/pages/ClassificationPage.tsx`:

Update the react-query import: `import { useMutation, useQuery, useQueryClient } from
"@tanstack/react-query";` and add `import { synchronizeKb, type SynchronizeKbResult } from
"../api/knowledge";`.

Inside the component, alongside the existing `useQuery`:

```ts
  const queryClient = useQueryClient();
  const [syncResult, setSyncResult] = useState<SynchronizeKbResult | null>(null);

  const syncMutation = useMutation({
    mutationFn: synchronizeKb,
    onSuccess: (result) => {
      setSyncResult(result);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
```

In the toolbar `<div className="mb-4">` block, next to the existing label filter `<input>`, add:

```tsx
        <button
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending}
          className="ml-2 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm font-semibold text-[var(--color-accent)] disabled:opacity-50"
        >
          {syncMutation.isPending ? "Syncing…" : "Sync Knowledge Base"}
        </button>
        {syncResult && (
          <span className="ml-3 font-mono text-xs text-[var(--color-text-faint)]">
            Indexed {syncResult.indexedJobIds.length}, skipped {syncResult.skippedCount}
          </span>
        )}
```

- [ ] **Step 2: Manual check** — not run; folded into Task 7's end-to-end walkthrough.

- [x] **Step 3: Run typecheck, lint, and tests**

`npx tsc -b && npm run lint && npm run test`: all clean, **20/20 tests passed**.

- [ ] **Step 4: Commit** — skipped, same git-workflow reason as Task 1.

---

### Task 6: Frontend — real Chat page (streaming RAG)

**Files:**
- Modify: `src/classiflow/frontend/src/pages/ChatPage.tsx`

**Interfaces:**
- Consumes: `apiFetch` from `../api/auth` directly (not through `api/knowledge.ts`, since this is
  a one-off streaming `fetch` call with manual body-reader parsing, not a typical
  request/response JSON call the rest of that module's shape fits).
- Produces: no new exports — same default export, still mounted at the existing `/chat` route
  with no router/nav changes needed.

- [x] **Step 1: Replace the stub with a streaming chat UI**

Replace the full contents of `src/classiflow/frontend/src/pages/ChatPage.tsx`:

```tsx
import { useState } from "react";
import { apiFetch } from "../api/auth";

interface Source {
  chunkId: string;
  filename: string;
  docType: string;
  number: string;
  year: string;
  subject: string;
  downloadUrl: string;
  excerpt: string;
  score: number;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  error?: boolean;
}

function parseSseEvents(buffer: string): { events: { type: string; data: string }[]; rest: string } {
  const events: { type: string; data: string }[] = [];
  const chunks = buffer.split("\n\n");
  const rest = chunks.pop() ?? "";
  for (const chunk of chunks) {
    const lines = chunk.split("\n");
    const eventLine = lines.find((l) => l.startsWith("event: "));
    const dataLine = lines.find((l) => l.startsWith("data: "));
    if (eventLine && dataLine) {
      events.push({ type: eventLine.slice("event: ".length), data: dataLine.slice("data: ".length) });
    }
  }
  return { events, rest };
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);

  async function handleSend(): Promise<void> {
    const q = question.trim();
    if (!q || isStreaming) return;
    setQuestion("");
    setMessages((prev) => [...prev, { role: "user", content: q }, { role: "assistant", content: "" }]);
    setIsStreaming(true);

    try {
      const response = await apiFetch("/knowledge/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      if (!response.ok || !response.body) {
        throw new Error(`POST /knowledge/chat/stream failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const { events, rest } = parseSseEvents(buffer);
        buffer = rest;

        for (const event of events) {
          if (event.type === "token") {
            const { text } = JSON.parse(event.data) as { text: string };
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = { ...next[next.length - 1], content: next[next.length - 1].content + text };
              return next;
            });
          } else if (event.type === "sources") {
            const sources = JSON.parse(event.data) as Source[];
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = { ...next[next.length - 1], sources };
              return next;
            });
          }
        }
      }
    } catch {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = { role: "assistant", content: "Something went wrong answering that question.", error: true };
        return next;
      });
    } finally {
      setIsStreaming(false);
    }
  }

  return (
    <div className="flex h-full flex-col p-6">
      <h1 className="mb-4 text-xl font-bold text-[var(--color-text)]">Chat</h1>
      <div className="flex-1 space-y-4 overflow-y-auto">
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
            <p
              className={`inline-block max-w-[75%] rounded-md px-3 py-2 text-sm ${
                m.role === "user"
                  ? "bg-[var(--color-accent)] text-[var(--color-bg)]"
                  : m.error
                    ? "bg-[var(--color-surface)] text-[var(--color-danger)]"
                    : "bg-[var(--color-surface)] text-[var(--color-text)]"
              }`}
            >
              {m.content || (isStreaming && i === messages.length - 1 ? "…" : "")}
            </p>
            {m.sources && m.sources.length > 0 && (
              <ul className="mt-1 space-y-1">
                {m.sources.map((s) => (
                  <li key={s.chunkId} className="font-mono text-[11px] text-[var(--color-text-faint)]">
                    <a href={s.downloadUrl} target="_blank" rel="noreferrer" className="hover:underline">
                      {s.filename}
                    </a>{" "}
                    · {s.docType} {s.number}/{s.year} — {s.excerpt}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      <div className="mt-4 flex gap-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="Ask a question about the indexed documents…"
          disabled={isStreaming}
          className="flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-faint)]"
        />
        <button
          onClick={handleSend}
          disabled={isStreaming || !question.trim()}
          className="rounded-md bg-[var(--color-accent)] px-4 py-2 text-sm font-semibold text-[var(--color-bg)] disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Manual check** — not run; folded into Task 7's end-to-end walkthrough.

- [x] **Step 3: Run typecheck, lint, and tests**

`npx tsc -b && npm run lint && npm run test`: all clean, **20/20 tests passed**.

- [ ] **Step 4: Commit** — skipped, same git-workflow reason as Task 1.

---

### Task 7: Whole-app verification pass

**Files:** none (verification only — no code changes expected).

**Interfaces:** N/A.

- [x] **Step 1: Full backend check**

`uv run poe check` from the repo root: **468 passed**, full pre-commit suite (ruff format/check,
mypy, frontend eslint/prettier, codespell, etc.) all green.

- [x] **Step 2: Full frontend check**

From `src/classiflow/frontend/`: `npx tsc -b && npm run lint && npm run test` — all clean,
**20/20 tests passed**. No cross-task regressions surfaced.

- [ ] **Step 3: End-to-end manual walkthrough** — **not run.** Requires both servers running
  live (backend `uvicorn`, frontend `npm run dev`), which needs to happen in a real browser —
  hand this to the user: upload a document → let it finish processing (auto-indexes into the
  KB) → open its Document Detail page and confirm the Knowledge Base tab shows its record →
  go to `/classification`, click "Sync Knowledge Base", confirm the result message → go to
  `/chat` and ask a question that should retrieve that document, confirming the streamed answer
  and its sources.

- [ ] **Step 4: Commit (only if Step 1-3 surfaced fixes)** — not applicable: the two fixes found
  during Task 2 (`conftest.py` override, `indexed_at` stamping) surfaced and were resolved
  within that task's own test-driven loop, not during this whole-app pass. No commits run
  regardless, per this repo's git-workflow policy (explicit per-message authorization
  required).

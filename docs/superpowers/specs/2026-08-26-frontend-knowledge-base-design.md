# Frontend Knowledge Base Integration — Design Spec

## Status

Decisions 8-12 implemented (see
`docs/superpowers/plans/2026-08-26-frontend-knowledge-base.md`, Tasks 1-6). Decision 13 was added
after manual testing surfaced a real bug in the Chat page's error handling (Task 7 in that same
plan). Decision 14 (below) was added after manual testing showed the Knowledge tab's municipal
metadata fields are populated by a runtime dependency (the `scrapper/` CSV dataset) that isn't
present in this checkout — see that decision for the root cause and the user's choice to defer
the real fix and instead hide the affected fields for now (Task 8 in the plan).

## Context

This spec extends `2026-08-25-frontend-visual-redesign-design.md`. That document explicitly
deferred one piece of scope:

> **No Chat page redesign.** It's an explicit placeholder for future Stage 5 (Knowledge Base +
> Chat Agent, not yet built) — restyling a stub with no real content ahead of that feature's own
> design pass would be wasted, throwaway work... Any real chat UI (message list, a form to send
> messages) belongs to that page's own future design pass, not this one.

Since that spec was written, Stage 5 (Knowledge Base + RAG) has landed on the backend:
`DocumentKb` model, an indexing pipeline that runs automatically after enrichment succeeds, a
`POST /knowledge/synchronize-kb` batch-reindex endpoint, and a full RAG chat service
(`POST /knowledge/chat`, `POST /knowledge/chat/stream`) all exist and are tested
(`tests/knowledge/*`, `tests/api/routes/test_knowledge.py`,
`tests/shared/test_pipeline_service_kb_sync.py`). None of it is wired into the frontend yet:
`ChatPage.tsx` is still the literal "Coming soon" stub, `DocumentDetailPage.tsx` has no
visibility into whether or how a document was indexed, and there's no UI trigger for the sync
endpoint.

This spec closes that gap. It is mostly a frontend wiring job — reusing the Archive visual
language and the `apiFetch` / TanStack Query conventions already established elsewhere in the
app — plus one small, well-scoped backend addition: a way to fetch a single document's KB
record, which doesn't exist yet (today the repository can only look a document up by `sha256`
or list every indexed document).

This document picks up the decision numbering where the visual redesign spec left off (that
spec's Decisions 1–7 are unchanged and not revisited here).

## Decisions

### 8. Backend: expose one document's KB record

**New repository method** — `find_by_job_id(job_id: str) -> DocumentKb | None`, added to:
- `IDocumentKbRepository` (`src/classiflow/domain/repositories/document_kb.py`)
- `SqlDocumentKbRepository` (`src/classiflow/database/repositories/document_kb.py`), via
  `select(DocumentKb).where(DocumentKb.job_id == job_id)` — `job_id` is already an indexed
  column, and this mirrors the existing `find_by_sha256` method's shape.
- `InMemoryDocumentKbRepository`, via a linear scan over the in-memory store.

**New schema**, in `src/classiflow/api/routes/knowledge/schemas.py`, following the existing
`SourceSchema.from_domain` pattern:

```python
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
    def from_model(cls, doc: DocumentKb) -> "DocumentKbSchema": ...


class DocumentKbResponse(BaseSchema):
    document_kb: DocumentKbSchema | None
```

The response returns `200` with `document_kb: null` for the not-yet-indexed case rather than
`404` — this mirrors `JobDetailResponse.enriched` / `.classification`, which are nullable rather
than erroring, since "not indexed yet" is an expected, normal state for a document, not a fault.

**New route**, in `src/classiflow/api/routes/knowledge/endpoints.py`, reusing the router's
existing `Depends(get_current_user)` and the existing `get_document_kb_repo` DI provider:

```python
@router.get("/documents/{job_id}")
async def document_kb(
    job_id: str,
    document_kb_repo: Annotated[IDocumentKbRepository, Depends(get_document_kb_repo)],
) -> DocumentKbResponse:
    doc = await document_kb_repo.find_by_job_id(job_id)
    return DocumentKbResponse(document_kb=DocumentKbSchema.from_model(doc) if doc else None)
```

**Tests:** extend `tests/api/routes/test_knowledge.py` with found/not-found cases for the new
route, and the document_kb repository test file with a `find_by_job_id` case.

### 9. Knowledge Base tab on Document Detail

**File:** `src/classiflow/frontend/src/pages/DocumentDetailPage.tsx`

- Add `"knowledge"` to the `Tab` union and `TABS` array (currently
  `type Tab = "extraction" | "enrichment" | "classification" | "audit"`). The tab strip itself
  needs no other change — it already maps generically over `TABS`.
- New `src/classiflow/frontend/src/api/knowledge.ts` module:
  ```ts
  export interface DocumentKbResponse {
    documentKb: {
      sha256: string; filename: string; docType: string | null; number: string | null;
      year: string | null; subject: string | null; sanctionDate: string | null;
      publicationDate: string | null; bulletinNumber: string | null;
      downloadUrl: string | null; chunkCount: number; indexedAt: string;
    } | null;
  }
  export async function fetchDocumentKb(jobId: string): Promise<DocumentKbResponse> { ... }
  ```
  Following the `apiFetch` + throw-on-`!ok` convention used throughout `api/*.ts`
  (e.g. `fetchJobDetail` in `api/documents.ts`).
- A second `useQuery` alongside the page's existing `job-detail` query — kept separate rather
  than merged into `JobDetailResponse`, since the KB record is served by its own endpoint:
  ```ts
  const { data: kb } = useQuery({
    queryKey: ["document-kb", jobId],
    queryFn: () => fetchDocumentKb(jobId!),
    enabled: !!jobId,
  });
  ```
- Tab content reuses the page's existing `KeyValueGrid` helper component for doc type, number,
  year, subject, dates, and download URL; `sha256` rendered truncated in mono; chunk count as a
  plain number; `indexedAt` formatted via `new Date(...).toLocaleString()` — matching the
  mono-for-IDs/timestamps, serif-for-values convention already used in the classification tab.
- Empty state when `kb?.documentKb` is `null`: a plain muted-text "Not indexed yet" message,
  matching the existing `No enrichment data` / `No classification data` empty-state style used
  by the other tabs in this file. No per-document reindex action in this pass — see Non-Goals.
- No changes to the PDF pane, the other tabs, or the existing `job-detail` query.

### 10. "Sync Knowledge Base" button on the Classification page

`synchronize-kb` reindexes every unindexed document system-wide — it is a global/batch action,
not scoped to one document — so its trigger belongs on the Classification page (the list of all
documents), not on Document Detail.

**File:** `src/classiflow/frontend/src/pages/ClassificationPage.tsx`

- Add to `api/knowledge.ts`:
  ```ts
  export interface SynchronizeKbResult { indexedJobIds: string[]; skippedCount: number }
  export async function synchronizeKb(): Promise<SynchronizeKbResult> { ... } // POST /knowledge/synchronize-kb
  ```
- Wire via `useMutation` (matching the pattern already used for `uploadDocuments` on the
  Processing page), placed in the toolbar row next to the existing label filter input:
  ```ts
  const syncMutation = useMutation({
    mutationFn: synchronizeKb,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });
  ```
  The button is disabled while `syncMutation.isPending`. On success, show an inline result
  message next to the button (e.g. "Indexed 3 documents, 12 already up to date") — there is no
  toast/notification system in this codebase to reuse, so a plain inline status string, cleared
  on the next click, matches the app's existing "no extra UI infrastructure" style.
- No backend change is needed here: `POST /knowledge/synchronize-kb` already exists and is
  already tested. This decision is pure frontend wiring.

### 11. Real Chat page

**File:** `src/classiflow/frontend/src/pages/ChatPage.tsx` — currently a 7-line stub already
routed at `/chat` and already present in `Sidebar.tsx`'s nav; no router or nav changes needed.

- **Layout:** a scrollable message list (serif type for message content, matching the app's
  body type) plus a bottom input row (textarea/input + send button), styled with the same
  surface/border/accent tokens used elsewhere in the app (e.g. the filter input on the
  Classification page, the form controls in `ReclassifyPanel`).
- **State:** local `useState` for the message list
  (`{ role: "user" | "assistant"; content: string; sources?: Source[] }[]`) plus an `isStreaming`
  flag. This is a manual async handler over `useState`, not a `useMutation` — react-query
  mutations resolve once and don't support incremental/streaming updates, and this codebase
  already has precedent for a manual-state action outside react-query (`ReclassifyPanel`'s
  submit handler) for exactly this kind of case.
- **Streaming transport:** a regular `apiFetch` call (which sets the `Authorization` header
  normally) against `POST /knowledge/chat/stream` — not `EventSource`, since this is a POST with
  a JSON body and `EventSource` only supports GET. Because this is a normal header-authenticated
  POST, none of the query-token workaround used for the GET-based `/pipeline/{id}/events` SSE
  stream is needed here — a normal Bearer header works fine on this endpoint.

  Consume the response via `response.body.getReader()` + `TextDecoder`, splitting on the
  `event: <type>\ndata: <json>\n\n` framing the backend already emits:
  - `event: token` → append `data.text` to the in-progress assistant message.
  - `event: sources` → attach the source list to that message.
  - `event: done` → end the stream, clear `isStreaming`.
- **Sources:** rendered under each assistant message as a small list (filename, doc type, year,
  excerpt, link via `downloadUrl`) — the fields already returned by the backend's `SourceSchema`.
- **Error handling:** on a fetch failure or a stream error, replace the in-progress assistant
  message with an inline error string, consistent with the plain-`Error`-throwing convention used
  throughout `api/*.ts`.
- **No filter UI in v1** — `ChatRequest.filters` stays `{}` from the frontend for now; doc_type/
  year narrowing controls are a possible future enhancement, not part of this pass (see
  Non-Goals).

### 12. Vite dev proxy

Add one entry to `src/classiflow/frontend/vite.config.ts`'s `server.proxy`:

```ts
"/knowledge": "http://127.0.0.1:8000",
```

A plain proxy target, not the `apiOnly()` wrapper used for `/classification`, `/users`, and
`/audit` — there is no frontend SPA route at `/knowledge`, so there's no page-load-vs-API-call
ambiguity to resolve for this prefix.

### 13. Chat stream error handling and logging

Found while manually verifying Decision 11: the Chat page accepted a question but never showed an
answer, and there was no way to tell why — it just looked like it hung.

**Root cause.** `POST /knowledge/chat/stream` is a `StreamingResponse`. Starlette sends the HTTP
response headers before pulling the first chunk from the body generator. Any exception raised
while streaming — an invalid/missing `ANTHROPIC_API_KEY`, a wrong `ANTHROPIC_MODEL`, a missing
local `.gguf` model file, a Chroma/retrieval error, or anything else inside `ChatService.astream()`
or either `ChatLlm` implementation — therefore happens *after* the response has already started.
Starlette's registered exception handlers (`src/classiflow/api/error_handlers/knowledge.py`,
`.../llm.py`) check `response_started` and cannot run once it's `True`; the connection just aborts
with no `event: done`, no error payload, and — since there was no logging anywhere in the chat
code path (`ChatService`, `RetrieverService`, `ClaudeChatLlm`, `LlamaCppChatLlm`, the route
handler) — no trace in the server logs either. This reproduces identically regardless of which
`CHAT_LLM_PROVIDER` is configured; it's a structural bug in how the endpoint handles mid-stream
failures, not a one-off misconfiguration. Contributing, smaller defect: `LlamaCppChatLlm._complete()`
(`src/classiflow/knowledge/llm/llama.py`) calls `get_chat_llm(...)` outside its own `try/except`,
so a missing model file raises `ModelNotFoundError`/`ModelLoadError` unwrapped instead of the
`ChatLlmError` the `ChatLlm` base class's contract promises — moot for the silent-hang symptom
itself (every exception dies the same way today) but worth fixing while touching this code.

**Fix.**
- `POST /knowledge/chat/stream`'s generator (`api/routes/knowledge/endpoints.py`) wraps its main
  loop in `try/except Exception`, logs the full exception via `logger.exception(...)`, and yields
  a new terminal SSE frame, `event: error` with `{"message": "..."}`, instead of `sources`/`done`
  — so the client gets a real terminal event instead of a dead connection.
- Every step of the RAG chain gains `loguru` logging (matching the existing convention elsewhere
  in the codebase, e.g. `services/pipeline/service.py`'s `logger.warning(...)` calls): retrieval
  chunk counts in `ChatService.astream()`, and the underlying provider error in both
  `ClaudeChatLlm` and `LlamaCppChatLlm` right before each is wrapped/re-raised as `ChatLlmError`.
  `LlamaCppChatLlm._complete()`'s contract violation is fixed alongside this (moved inside the
  `try/except`).
- `ChatPage.tsx` handles the new `error` event type and logs to `console.error` (the codebase's
  frontend had zero `console.*` usage anywhere before this — a deliberate, explicitly diagnostic
  exception to that absence, not a new general convention).

**UX decision (made with the user):** the chat bubble shown to the end user stays generic
("Something went wrong answering that question.") regardless of the actual failure — the real
exception detail goes only to server logs (`logger.exception`, full traceback) and the browser
console (`console.error`). This matches the app's non-technical municipal-reviewer audience
(per the visual redesign spec's Audience & Direction section) while still giving a developer a way
to see exactly what failed, without exposing internal error strings (auth failures, model paths,
provider stack traces) to end users. The non-streaming `POST /knowledge/chat` endpoint doesn't
have this bug — its exceptions happen before any response starts, so the registered handlers
already work correctly there — so it needed no equivalent fix.

### 14. Knowledge tab: hide unpopulated metadata fields, add an Indexed column, show sync progress

Found while manually testing the Knowledge Base tab (Decision 9): almost every field renders as
"—" — Doc Type, Number, Year, Subject, Sanction Date, Publication Date, Bulletin Number.

**Root cause.** These fields are resolved by `CsvDocumentMetadataRepository`
(`src/classiflow/knowledge/indexing/csv_metadata.py`), which parses the filename against a
`{tipo}_{numero}_{anio}.pdf` pattern and looks up a matching row across 9 CSVs
(`boletines.csv`, `decretos.csv`, `ordenanzas.csv`, etc.) expected at `SCRAPPER_DIR`
(`.env`: `./scrapper`). That directory doesn't exist in this checkout — it was intentionally
removed in commit `60f1d64` ("Phase 1 ingestion already completed its job -- the downloaded
documents live on Google Drive"). Every CSV lookup silently fails `path.exists()`, so
`resolve()` degrades to `DocumentMetadata(filename=filename)` for every document — logged as a
`logger.warning`, never surfaced as an error, which is why nothing caught this earlier. This is
purely a missing-data problem, not a code defect: confirmed the `knowledge/` package never reads
PDFs or does OCR (`IndexerService.index()` only consumes `record.cleaned_text`; the package's
only file-open call is a CSV read) — the pipeline-stage separation this feature was built on is
intact. Also confirmed no cleaner alternative metadata source exists yet elsewhere in the
pipeline: `EnrichedRecord` carries no dedicated columns for this data, and its `entities` JSON
only has a partial, LLM-guessed subset (no subject/dates/bulletin/URL, and a `year` type
mismatch) — there's no municipal-dataset batch ingester in this codebase that captures this
metadata at ingestion time either.

**Decision made with the user:** defer the real fix (the CSVs are actually recoverable — they
were committed to git before removal, at commit `0e27d4f`, the parent of `60f1d64` — restoring
them plus backfilling already-indexed `document_kb` rows is a pure data/config fix with no
pipeline code changes) and instead ship three smaller, immediate UI improvements:

- **Hide the seven always-blank fields** (Doc Type, Number, Year, Subject, Sanction Date,
  Publication Date, Bulletin Number) from the Knowledge tab for now, rather than showing a wall
  of "—" placeholders. Filename, SHA-256, Chunk Count, Indexed At, and the already-conditional
  Download URL are unaffected. This is a display-only change — `DocumentKbSchema`/
  `DocumentKbResponse` keep returning these fields; when the metadata is eventually restored, the
  UI rows come back with a small revert of this change.
- **Add an "Indexed" column to the Classification grid**, showing `document_kb.indexed_at` per
  row (blank for documents not yet indexed) — reuses the `IDocumentKbRepository.find_by_job_id`
  method added for Decision 8, called once per row inside `GET /jobs`'s existing per-job loop
  (which already does the same shape of lookup for classification data) — no new endpoint, no new
  repository method.
- **Show a visible in-progress state** while "Sync Knowledge Base" is running (a pulsing accent
  dot + status text), reusing the same `animate-pulse`/`--color-accent` "live state" convention
  already established by the visual redesign spec's Decision 7 rather than introducing a new
  spinner pattern.

## Non-Goals

- **No filter controls** (doc_type/year) in the Chat UI for v1.
- **No per-document reindex action.** The only indexing trigger exposed in the UI is the
  existing global `synchronize-kb` batch action; a document with no KB record just shows a
  view-only "Not indexed yet" state. (`index_enriched_record`, the per-document indexing method,
  already exists on `PipelineService` but is not exposed over HTTP — adding that route is future
  scope, not part of this pass.)
- **No revision of the visual redesign spec's Decisions 1–7** (tokens, layout shell, the
  phase-grouped timeline, Processing/Classification/Users/Audit Log page treatments, motion) —
  this document only adds new scope on top of that spec; the pages it touches already inherit
  the shared shell/token treatment for free.
- **No changes to indexing/chunking/embedding/retrieval/LLM-provider internals** — those already
  work and are out of scope. This spec is exposing existing data (the per-document KB record) and
  wiring already-existing, already-tested endpoints (`synchronize-kb`, `chat`, `chat/stream`)
  into the UI.
- **No centralized logging infrastructure** (Decision 13 adds targeted `loguru` calls to the
  existing default stderr sink only — no file sinks, log-level configuration, or structured JSON
  logging).
- **Not diagnosing or fixing the actual chat misconfiguration itself** (if any) — Decision 13
  makes failures visible; whatever the logs turn out to say (missing API key, wrong model path,
  etc.) is a separate follow-up once known.
- **Not restoring the `scrapper/` CSVs or backfilling existing blank `document_kb` rows**
  (Decision 14) — explicitly deferred by the user this pass; a separate follow-up once decided.
- **No sortable "Indexed" column** — not requested; would also need extending the backend's
  `SortField`/`_sort_summaries`.
- **No changes to `CsvDocumentMetadataRepository`, `IndexerService`, or the metadata-resolution
  logic itself** (Decision 14) — the existing filename+CSV lookup is correct, it just has no data
  to read right now; this pass only changes what the UI shows, not how resolution works.

## Testing

- **Backend:** extend `tests/api/routes/test_knowledge.py` with found/not-found cases for
  `GET /knowledge/documents/{job_id}`, and add a `find_by_job_id` case to the document_kb
  repository test file.
- **Frontend:** a component-level test for the Knowledge Base tab's indexed vs. not-indexed
  states; a test for the Classification page's sync button covering its pending/success states;
  a test for the Chat page's streamed-message-append behavior (mocking `fetch`'s
  `ReadableStream`) — following the existing convention of component tests for pieces with real
  branching logic (`StepTimeline.test.tsx`, `ReclassifyPanel.test.tsx`, `RequireAdmin.test.tsx`).
- Run `uv run poe check` (lint + typecheck) and the frontend's own Vitest suite per the project's
  standard verification gate — hand these commands to the user to run rather than executing them
  directly, per this repo's execution-workflow rule (notebooks/test suites are always run by the
  user, never in the background by Claude).
- **Decision 13** is verified manually rather than with new automated tests, since it's a
  logging/observability change: reproduce a chat question with the backend running, confirm the
  server's stderr shows the new `loguru` lines (retrieval chunk count, provider errors if any) and
  — if the underlying provider still fails — that a generic `event: error` frame now reaches the
  UI (a real error bubble, not a silent hang) with matching `console.error` output in the browser.
- **Decision 14:** manual verification — confirm `GET /jobs` now includes `indexedAt` (null for
  unindexed documents, a real timestamp for indexed ones); confirm the Classification grid renders
  the new Indexed column; confirm the Knowledge tab no longer shows the seven blank metadata rows;
  confirm clicking "Sync Knowledge Base" shows the pulsing in-progress indicator while running.

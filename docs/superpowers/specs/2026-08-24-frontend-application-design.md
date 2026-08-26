# Classiflow Frontend Application — Design

## Status

Approved by user, section by section, 2026-08-24. Ready for implementation planning.

## Context

Classiflow's backend (Stages 1-4: ingesta, extraction hardening, enrichment,
classification & routing) is fully built and merged to `main`. There is no frontend at
all today — the only way to interact with the system is direct API calls. This spec
designs the first UI: a React SPA giving operators visibility into running jobs, a
browsable history of classified documents with full per-document drill-down (PDF +
extraction + enrichment + classification + audit trail), the ability to manually
resolve documents stuck in human review, user access management, and an audit log for
administrative oversight. A placeholder Chat page reserves the nav slot for Stage 5
(not yet built).

This is new-subsystem work (frontend didn't exist; several new backend endpoints are
needed to support it) — classified as **architectural** per the brainstorming skill.

## Non-Goals

- Building Stage 5 (Knowledge Base + Chat) itself — only a placeholder page.
- Real-time multi-tab/multi-user event fan-out beyond what `EventBroadcaster`'s
  existing per-process `asyncio.Queue` already provides — no message bus, no Redis.
- A general-purpose role system — only a single `is_admin` boolean, not a role/permission
  matrix. Add more roles later if a real second tier is ever needed (YAGNI).
- Offline support, PWA behavior, or mobile-native apps.
- Server-side rendering — this is an internal tool behind OAuth, not a public site.
- Rewriting or restructuring any existing backend module. All backend changes in this
  spec are additive (new columns, new endpoints) or minimally invasive (extending
  `User`/`AuthService`'s return shape).

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│               src/classiflow/frontend (React SPA)                │
│                                                                  │
│  Pages: Login · Processing · Classification · DocumentDetail ·  │
│         Users (admin) · AuditLog (admin) · Chat (placeholder)   │
│                                                                  │
│  api/        typed fetch wrappers, one module per resource      │
│  auth/       AuthContext, popup OAuth flow, token storage       │
│  components/ StepTimeline, PdfViewer, DataTable, StatusBadge    │
└───────────────────────────┬──────────────────────────────────────┘
                             │ HTTPS (JSON + SSE), Bearer JWT
                             ▼
┌────────────────────────────────────────────────────────────────┐
│                  FastAPI backend (existing + new)                │
│                                                                  │
│  Existing: /auth/*, /pipeline/*, /classification/*               │
│  New:      /jobs, /jobs/{id}/detail, /jobs/{id}/timeline,        │
│            /documents/{id}/file, /users/*, /audit, /auth/me      │
└────────────────────────────────────────────────────────────────┘
```

## Decision 1 — Frontend stack and location

**Location**: `src/classiflow/frontend/` — inside the `classiflow` Python package
itself, per explicit user direction. Its own `package.json`, `node_modules/`,
`tsconfig.json` live there, fully separate toolchain from `uv`/Python — but because
`src/classiflow/` is a real importable package (has `__init__.py`, gets built/packaged
via `pyproject.toml`), `frontend/` must be explicitly excluded from Python tooling so
it isn't mistaken for Python source:
- **ruff**: `pyproject.toml`'s `[tool.ruff] exclude` already lists
  `[".claude", "tasks", "alembic", "models"]` (line 96) — add `"src/classiflow/frontend"`
  to that list (lint/format must not walk `node_modules/` or `.tsx`/`.ts` files).
- **mypy**: `[tool.mypy] exclude` already lists `["src/classiflow/playground/"]`
  (line 157) — add `"src/classiflow/frontend/"` alongside it.
- **packaging**: the build backend is `hatchling`
  (`[tool.hatch.build.targets.wheel] packages = ["src/classiflow"]`, line 86), which
  would otherwise sweep the whole `frontend/` subtree into the built wheel. Add
  `[tool.hatch.build.targets.wheel] exclude = ["src/classiflow/frontend"]` (or the
  equivalent `artifacts`/`exclude` key hatchling expects — confirmed exact key name
  during plan execution, not guessed here) so `pip install classiflow` never ships
  `node_modules/`.
- **`.gitignore`**: `src/classiflow/frontend/node_modules/` and
  `src/classiflow/frontend/dist/` added, matching how `.venv/` is already ignored for
  the Python side.

**Stack**: React 19 + TypeScript + Vite, matching the sibling `bert_tunning/frontend`
project's stack (reviewed at the user's request and reused where it fits: same
toolchain, lint/format tooling, and TS strictness) rather than inventing a new
convention:
- **Routing**: `react-router` — client-side routes for all pages (not present in
  `bert_tunning/frontend`, added here since this app has 7 pages vs. its single-page
  form; everything else below is carried over).
- **Data fetching**: `@tanstack/react-query` for request/cache/refetch of list and
  detail endpoints; the native `EventSource` API for SSE (no library needed — it's a
  browser built-in).
- **PDF viewer**: `react-pdf` (wraps `pdf.js`) — renders bytes streamed from
  `GET /documents/{job_id}/file` directly in-browser.
- **Styling**: Tailwind CSS v4 via `@tailwindcss/vite` (no PostCSS config file needed —
  matches `bert_tunning/frontend`'s setup), dark-only palette via CSS variables for the
  handful of colors that vary (status dots, label badges, review-route colors).
- **Forms**: plain controlled components — the app has exactly two real forms (User
  CRUD, Reclassify), not enough to justify a form library.

**Linting, formatting, and TypeScript strictness** (carried over from
`bert_tunning/frontend`'s config, reviewed directly):
- **ESLint**: flat config (`eslint.config.js`) via `typescript-eslint`, `@eslint/js`
  recommended rules, `eslint-plugin-react-hooks` recommended rules,
  `eslint-plugin-react-refresh` (`only-export-components` warn), and
  `eslint-config-prettier` last in the `extends` chain to disable any formatting rules
  that would conflict with Prettier.
- **Prettier**: `.prettierrc` — `{ "semi": true, "singleQuote": false, "trailingComma":
  "all", "printWidth": 100 }`. `printWidth: 100` intentionally matches this repo's
  Python `line-length = 100` (`pyproject.toml`'s `[tool.ruff]`), so both toolchains
  wrap at the same column.
- **TypeScript**: project-references split (`tsconfig.json` referencing
  `tsconfig.app.json` + `tsconfig.node.json`, the latter for `vite.config.ts` itself),
  `target: es2023`, `moduleResolution: bundler`, `noUnusedLocals`/`noUnusedParameters`/
  `noFallthroughCasesInSwitch` all on — TypeScript's own strictness bar mirrors this
  project's `mypy strict` requirement for the Python side.
- **Git hooks — deliberate deviation**: `bert_tunning/frontend` uses `husky` +
  `lint-staged` for its own pre-commit hook. This repo already has a single
  repo-wide hook manager — the Python `pre-commit` framework
  (`.pre-commit-config.yaml`) — so this spec does **not** add husky (a second,
  competing git-hooks manager would fight over `.git/hooks/pre-commit`). Instead, a new
  `repo: local` entry is added to the existing `.pre-commit-config.yaml` running
  `npm --prefix src/classiflow/frontend run lint` (ESLint) and
  `npx --prefix src/classiflow/frontend prettier --check .` (or an equivalent combined
  `npm run lint` script covering both), gated to only run when frontend files changed,
  matching how the existing `mypy` hook is scoped to `files: ^src/`.
- **Dev server proxy**: `vite.config.ts`'s `server.proxy` forwards API paths
  (`/auth`, `/pipeline`, `/classification`, `/jobs`, `/documents`, `/users`, `/audit`)
  to the local FastAPI dev server (`http://127.0.0.1:8000`), the same pattern
  `bert_tunning/frontend` uses for its own backend — avoids CORS configuration
  entirely for local development.

**Directory layout:**
```
src/classiflow/frontend/
├── src/
│   ├── api/              jobs.ts · documents.ts · users.ts · audit.ts · auth.ts
│   ├── pages/             LoginPage · ProcessingPage · ClassificationPage ·
│   │                      DocumentDetailPage · UsersPage · AuditLogPage · ChatPage
│   ├── components/        StepTimeline · PdfViewer · DataTable · StatusBadge ·
│   │                      Sidebar · RequireAuth · RequireAdmin
│   ├── auth/               AuthContext.tsx · oauthPopup.ts · tokenStorage.ts
│   ├── App.tsx · main.tsx · router.tsx
├── package.json
├── vite.config.ts
└── tsconfig.json
```

## Decision 2 — Authentication: popup OAuth, unchanged backend response shape

The existing `/auth/login` → Google → `/auth/callback` flow returns `AuthToken`
(`{access_token, token_type}`) as a **JSON response body**, not a redirect. Per
explicit user decision, this shape stays exactly as-is — no backend redirect-into-SPA
change.

**Flow**: the SPA opens `/auth/login` in a popup window (`window.open`). The user
completes Google's consent screen; Google redirects the popup to `/auth/callback`,
which returns the `AuthToken` JSON as today. A tiny static page served at that same
origin (or the callback response itself, rendered as a minimal auto-executing HTML
page — see plan for exact mechanism) reads that JSON and relays it to the opener
window via `window.opener.postMessage({ type: "oauth-token", token }, origin)`, then
closes itself. The main window's `AuthContext` listens for that `message` event, stores
the token, and closes the popup if it hasn't already.

**Token storage**: `localStorage`. `AuthContext` reads it on load, exposes
`{ user, isAdmin, login(), logout() }` to the app. Every `api/*` fetch wrapper attaches
`Authorization: Bearer <token>`. A `401` response clears the stored token and redirects
to `/login`.

**New endpoint — `GET /auth/me`**: protected (`Depends(get_current_user)`), returns the
current user's `{ email, is_admin }`. Called once after token storage to populate
`AuthContext` — the JWT itself stays unchanged (still just `sub=email`); `is_admin` is
looked up fresh from `AllowedUser` on every call, consistent with how
`AuthService.verify_token` already re-checks `is_allowed` against the DB rather than
trusting a stale claim.

## Decision 3 — `AllowedUser.is_admin` and `AuthService` changes

**Migration**: add `is_admin: Mapped[bool] = mapped_column(Boolean, default=False,
nullable=False)` to `AllowedUser` (`database/models.py`), new Alembic revision
`0008_add_allowed_user_is_admin.py`.

**`domain/user.py`**: `User` gains `is_admin: bool = False`.

**`services/auth/service.py`**: `AuthService.verify_token` currently only calls
`is_allowed(payload.sub)` (a bool check) and constructs `User(email=payload.sub)`
without ever fetching the full row. It needs to fetch the `AllowedUser` row itself
(via `IUserRepository.find_by_email` — already exists) to read `is_admin`, and
construct `User(email=payload.sub, is_admin=allowed_user.is_admin)`.

**`is_blocked` is already enforced** — `IUserRepository.is_allowed` (both `Sql`/
`InMemory` implementations, `database/repositories/user.py`) already checks
`user.is_active and not user.is_blocked`, and `AuthService.verify_token` already calls
`is_allowed` on every request. The Users page (Decision 6) exposing `is_blocked` as an
editable field is therefore a real, working "block this user" control from day one, no
further backend change needed — corrected from an earlier draft of this spec that
incorrectly assumed it was unenforced.

**No changes to `AuthToken` or the JWT payload shape** — `is_admin` is derived
per-request from the DB, exactly like the allow-list check already is.

## Decision 4 — Queued vs. processing status (throttling/backpressure visibility)

`PipelineService` already bounds concurrency via `self._job_semaphore`
(`asyncio.Semaphore`, sized by `Settings.MAX_CONCURRENT_JOBS`, default 2) — jobs beyond
that limit wait for the semaphore inside `_run()` before doing any real work. Today's
`Job.status` can't distinguish "accepted, waiting for a slot" from "actively running a
pipeline node": `start()` sets `status="started"` the instant the row is created,
before the semaphore is ever touched, and it doesn't change again until the whole
pipeline finishes.

This is a small, additive fix, not a pipeline redesign — one new status value, one new
DB write, one new broadcast event, all inside `PipelineService`:
- `PipelineService.start()` (`services/pipeline/service.py:82`): create the `Job` row
  with `status="queued"` instead of `"started"`.
- `PipelineService._run()` (`services/pipeline/service.py:88`): immediately after
  acquiring the semaphore (`async with self._job_semaphore:`), call
  `self._job_repo.update_status(job_id, "processing")` and emit a
  `NodeEvent(job_id=job_id, node=_PIPELINE_NODE, status=JobStatus.PROCESSING)` via the
  broadcaster, mirroring the existing `JobStatus.DONE` emit at the end of `_run()`.
- `domain/job.py`: `JobStatus` gains `PROCESSING = "processing"`. `Job.status` is a
  free-text `String(20)` column (not DB-enum-constrained), so no migration is needed
  for the new `"queued"`/`"processing"` string values themselves.
- No change to the semaphore, retry logic, `_persist_steps`, `_finalize_job`, or any
  node/coordinator — this only adds visibility into a state transition that already
  happens, it doesn't change when or how jobs run.

The Processing page (Decision 6) uses this to show two distinct groups: **Queued**
(waiting for a concurrency slot) and **Processing** (actively running, has a live step
timeline). This is the extent of what changes — no queue data structure, no message
bus, no rejection/backpressure signal to the uploader; excess uploads still just wait
in-process for the semaphore, as they do today.

## Decision 5 — New backend endpoints

All new endpoints live under existing routers where they fit the resource, or a new
`users` / `audit` router otherwise. All require `Depends(get_current_user)`; `/users/*`
and `/audit` additionally require a new `Depends(require_admin)` dependency
(`api/dependencies.py`) that raises `403` if `CurrentUser.is_admin` is `False`.

**`GET /pipeline/jobs`** (query: `status` — `running` | `all`, default `running`;
`running` matches both `"queued"` and `"processing"` rows, per Decision 4)
Returns `list[JobSummary]` (`job_id, filename, status, created_at, updated_at,
current_node`). `status` in the response is the literal `Job.status` value
(`"queued"` or `"processing"` for in-flight jobs), so the Processing page can group by
it directly. Backs the Processing page's initial list and the Classification page when
`status=all` combined with the filter params below.

**`GET /pipeline/jobs/{job_id}/timeline`**
Returns the backfill for a single job: a merged, chronologically ordered list of
`DocumentStep` rows (Stage 1/2 nodes) and `AuditRecord` rows (Stage 3/4 nodes, which
only write to `audit_records`, not `document_steps`) as one `list[TimelineEntry]`
(`node, status, passed, detail, timestamp, duration_ms`). The Processing page calls
this once per visible running job on mount, then layers live SSE events
(`GET /pipeline/{job_id}/events`, unchanged) on top for anything after that snapshot.

**`GET /jobs`** (query: `label`, `review_route`, `date_from`, `date_to`, `q` — filename
search, `page`, `page_size`)
Paginated, filterable list of completed jobs (`status != running`) joined with their
`ClassificationRecord` if one exists, for the Classification table page. Returns
`PaginatedResponse[ClassificationSummary]`.

**`GET /jobs/{job_id}/detail`**
One aggregate response for the Document Detail page's tabs:
`{ job: JobDetail, enriched: EnrichedRecordSchema | None,
classification: ClassificationRecordSchema | None, audit: list[AuditRecordSchema] }`.
Assembles data already collected by four existing repositories
(`IJobRepository`, `IEnrichedRecordRepository`, `IClassificationRecordRepository`,
`IAuditRepository.list_for_job` — `services/audit/repository.py`, already exists) — no
new persistence, purely a read-side aggregation endpoint.

**Repository extension needed**: `IAuditRepository` (`services/audit/repository.py`)
already exists with `save`/`list_for_job`, but has no paginated, filterable "list all"
method — only per-job lookup. This spec adds a `list_filtered(job_id, node, event,
date_from, date_to, page, page_size)` method to the Protocol and both its `Sql`/
`InMemory` implementations, to back the new `GET /audit` endpoint.

**`GET /documents/{job_id}/file`**
Streams the PDF bytes for viewing. Resolves the current on-disk path the same way
`LocalDiskStorage._move_to_final_sync` already does (glob under the storage root for
`{job_id}_*`, since a document may still be in `staging/`, `review/human_review/`, or
`classified/<label>/` depending on its state) and returns a `StreamingResponse` with
the appropriate `Content-Type` (`application/pdf` or the original upload's MIME type,
read from the existing format-validation result if non-PDF types are ever routed here
— PDFs are the only case exercised by this spec's UI, per the corpus).

**`GET/POST/PATCH/DELETE /users`** (admin-only)
Standard CRUD over `AllowedUser`: list, create (`email`, `is_admin`), update
(`is_active`, `is_admin`, `is_blocked`), delete. Backed by a new
`IUserRepository` methods (`list_all`, `create`, `update`, `delete`) added to the
existing Protocol + its `Sql`/`InMemory` implementations, following the project's
established repository pattern.

**`GET /audit`** (admin-only; query: `job_id`, `node`, `event`, `date_from`, `date_to`,
`page`, `page_size`)
Paginated, filterable listing directly over `audit_records`, for the Audit Log page.
Each row links to its job (`job_id`), enabling click-through to that job's Document
Detail page.

## Decision 6 — Pages

### Login
Single "Sign in with Google" button. Triggers the popup OAuth flow (Decision 2). On
success, redirects to `/` (Processing).

### Processing (live dashboard of running jobs)
Fetches `GET /pipeline/jobs?status=running` on mount and on an interval (e.g. every
10s, as a safety net alongside SSE). Jobs render in two grouped sections — **Queued**
(`Job.status == "queued"`: accepted, waiting for a concurrency slot per Decision 4's
`job_semaphore` — shown as a lightweight row, no step timeline yet since nothing has
run) and **Processing** (`Job.status == "processing"`: a full job card with filename,
job_id, and a vertical step timeline — dot + bold step name + live status line,
matching the reference image's style — backfilled via
`GET /pipeline/jobs/{job_id}/timeline` then updated live via
`GET /pipeline/{job_id}/events`, `EventSource`). A queued job moves into the
Processing section the moment its `NodeEvent(status=JobStatus.PROCESSING)` event
arrives (or on the next interval refetch); a job disappears from both sections once
its terminal event fires.

### Classification (historical documents, table + filters)
A filterable, searchable, paginated table backed by `GET /jobs`. Filters: label,
review_route, date range, filename search. Columns: filename, label, review_route,
confidence, judged_by_llm, created_at. Clicking a row navigates to that document's
Detail page. Rows with `review_route == human_review` get a visible badge (not an
inline action — reclassify lives on the Detail page, described next).

### Document Detail (`/documents/:jobId`)
Split view: PDF viewer (`react-pdf`, fed by `GET /documents/{job_id}/file`) pinned on
the left (stacks above on narrow viewports); a tab strip on the right —
**Extraction** (raw + cleaned text), **Enrichment** (entities, metadata),
**Classification** (primary label/confidence/all_scores, second opinion label/
confidence, OOD metrics, SVM scores, smells/risk_score, foreign_municipality,
judge verdict if `judged_by_llm`, stored_path), **Audit Trail** (this job's
`audit_records`, chronological). All four tabs' data comes from the single
`GET /jobs/{job_id}/detail` call.

**Reclassify**: when `classification.review_route == "human_review"`, the
Classification tab shows a reclassify panel — label dropdown (11 `DocumentCategory`
values) + notes field — submitting to the existing
`POST /classification/{job_id}/decision` endpoint (no backend change needed here, it
already exists and already does the right thing).

### Users (`/users`, admin-only)
Table of `AllowedUser` rows (email, is_active, is_admin, is_blocked, created_at) with
add/edit/delete actions, backed by the new `/users` CRUD endpoints. Guarded by
`RequireAdmin` — a non-admin hitting this route directly is redirected to `/`, not just
denied a nav link.

### Audit Log (`/audit`, admin-only)
Full `audit_records` table, filterable by job_id/node/event/date range, paginated.
Each row links to its job's Detail page. Guarded by `RequireAdmin`, same pattern as
Users.

### Chat (`/chat`, placeholder)
Reserves the nav slot for Stage 5. Renders a "Coming soon — Stage 5" message. No chat
UI, no backend calls. Visible to all authenticated users (not admin-gated — Stage 5 is
planned for everyone, not an admin feature).

## Decision 7 — Navigation and access control

Persistent dark sidebar: Processing, Classification, Chat always visible; Users and
Audit Log rendered only when `AuthContext.isAdmin` is true. Two route guards:
- `RequireAuth` — wraps every route except `/login`; redirects to `/login` if no valid
  token.
- `RequireAdmin` — wraps `/users` and `/audit`; redirects to `/` if `!isAdmin`. This is
  a real guard (checked on every navigation, not just a hidden nav link), since a
  non-admin user typing the URL directly must not reach the page.

## Testing Strategy

- **Backend**: standard project pattern — `InMemory*` repository tests for new
  endpoints' service-layer logic (job listing/filtering, timeline merge/ordering, user
  CRUD, audit filtering), FastAPI `TestClient` tests for each new route including the
  `require_admin` 403 case.
- **Frontend**: component tests (Vitest + React Testing Library) for `StepTimeline`
  (backfill + live-event merge logic — the trickiest piece), `RequireAdmin`/
  `RequireAuth` guards, and the Reclassify form's submit flow against a mocked API.
  No E2E framework introduced in this spec — out of scope, can be added later if
  justified.

## Open Risks / Things Confirmed Out of Scope

| Risk | Disposition |
|---|---|
| `EventBroadcaster` is in-memory, single-process — SSE only reflects events from the server instance handling that connection | Accepted; timeline backfill (Decision 5) is what makes "see where processing is" reliable regardless of tab/reconnect timing, not a promise that SSE itself survives a server restart |
| `GET /documents/{job_id}/file` path resolution reuses `LocalDiskStorage`'s glob-by-`{job_id}_*` approach, which assumes exactly one physical file per job (true today, per existing code comments) | Accepted as-is; not re-verified beyond what `LocalDiskStorage` already guarantees |
| Non-PDF uploads (DOCX, images) aren't given a viewer treatment beyond raw streaming in this spec | Acceptable per current corpus (PDF-only in practice); `react-pdf` will simply not render non-PDF bytes — flagged, not solved, here |
| `TYPE_CHECKING` already appears in `api/dependencies.py` (pre-existing) | Out of scope — this spec's additions to that file follow the existing top-level-import convention for anything new, per `CLAUDE.md`, without touching the existing `TYPE_CHECKING` block |

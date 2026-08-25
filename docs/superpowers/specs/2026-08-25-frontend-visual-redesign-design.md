# Frontend Visual Redesign — Design Spec

## Context

The Classiflow frontend (`src/classiflow/frontend/`) was built functionally-first: React 19 +
Vite 6 + Tailwind v4, dark theme, all pages working end-to-end. It has never had a real design
pass applied at the system level — `src/index.css` defines one generic dark palette (system
font, blue accent, no type scale), and every page is built from plain Tailwind utility classes
with no layout rhythm or visual hierarchy. The one exception is `StepTimeline.tsx`, which got an
isolated design pass earlier (via the `frontend-design` skill) but was never extended to the rest
of the app, so it reads as a single polished component floating in an otherwise undesigned shell.

Two problems triggered this spec:

1. **Job state isn't legible.** A document moves through four real backend phases — ingesta
   (4 nodes), enrichment (3 nodes), classification (5+ nodes), routing — but the Processing page
   only ever showed a flat, mostly-empty timeline, and (per a same-session backend fix) `Job.status`
   used to flip to a terminal value the instant Stage 1 finished, making jobs vanish from the
   Processing page's "running" query while enrichment/classification (the slow, multi-minute part)
   was still running. The backend fix (`Job.status` now stays `"processing"` until the whole
   pipeline including classification+routing finishes, landing on a new terminal `"classified"`
   status) is already shipped and tested; this spec is about the frontend actually surfacing that
   state well once it's true.
2. **General visual quality.** The user's own words: the app "seems like a junior built it."
   Every page — Processing, Classification, Document Detail, Users, Audit Log — needs a real
   design pass, not just the one component that already got one.

This is scoped as the whole app (all pages), not just Processing, per explicit user choice when
asked to scope it.

## Audience & Direction

**Audience:** municipal reviewers/clerks — non-technical staff monitoring document processing and
reviewing flagged documents. The design should read as approachable and trustworthy, not a raw
technical/ops dashboard, while still surfacing the real pipeline mechanics (full step-by-step
history, not just "done/not done") since that's what this audience explicitly asked to see.

**Visual direction — "Archive."** Validated with the user via the visual companion (mockups shown
side-by-side against two alternatives — "Municipal Slate" cool graphite/teal, and "Signal"
near-black/amber — both rejected in favor of Archive). Warm paper-ink palette, serif display type,
terracotta/olive accents, monospace for utility text (IDs, timestamps, node names). It reads as a
municipal records office, not a SaaS admin panel — appropriate for a government back-office tool
serving non-technical staff, and distinctive without being flashy (the user's own "distinctive but
restrained" framing from Decision 1 below).

**Signature element:** the phase-grouped timeline itself. Not a decorative one-off — it's reused
everywhere a document's journey through the pipeline is shown: full-size on the Processing page,
condensed to a one-line phase summary in the Classification table (future enhancement, not
required by this spec — see Non-Goals), and as the structure behind the Document Detail page's
Audit tab. One real content-driven idea, applied consistently, rather than a hero graphic bolted
onto the top of one page.

## Decisions

### 1. Token system

Replace `src/index.css`'s current five-color, no-type-scale palette with a real token system.
Colors as named hex values (validated against the companion mockups):

```css
:root {
  /* Backgrounds */
  --color-bg: #14110f;           /* page background */
  --color-bg-inset: #100d0a;     /* sidebar / recessed panels */
  --color-surface: #1b1712;      /* cards, table rows */
  --color-surface-hover: #221d16;

  /* Borders */
  --color-border: #322a20;       /* card/table borders */
  --color-border-subtle: #2a2319; /* internal dividers, timeline rail */

  /* Text */
  --color-text: #f2ead9;         /* primary text (warm off-white) */
  --color-text-muted: #a89a80;   /* secondary text */
  --color-text-faint: #6b5f4d;   /* labels, timestamps, disabled */
  --color-text-pending: #57503f; /* not-yet-reached pipeline steps */

  /* Accents */
  --color-accent: #c1663a;       /* terracotta — primary accent, live/in-progress state */
  --color-success: #6b8f5a;      /* olive green — passed/accepted/done */
  --color-warning: #d49d3c;      /* amber — human review, smells */
  --color-danger: #b5453a;       /* muted red-terracotta — failed/rejected, NOT the bright
                                     red of the old palette; stays in-family with the warm
                                     palette instead of clashing against it */
}
```

Type: `Georgia, 'Times New Roman', serif` for display/headings and body text (already validated
in the mockups — no webfont dependency, ships everywhere, matches the "paper/archive" framing
without adding a font-loading step). `'Courier New', ui-monospace, monospace` for utility text:
job IDs, node names, timestamps, confidence scores. This two-face pairing (serif for reading,
mono for machine-generated data) is the entire type system — no third face needed.

Both are system fonts. **No Google Fonts / webfont import** — keeps the existing zero-network-font
setup, avoids a FOUC/layout-shift concern, and both faces are already what the validated mockups
used.

### 2. Layout shell

Sidebar (`Sidebar.tsx`) restyled: `--color-bg-inset` background, serif "Classiflow" wordmark in
`--color-accent`, nav items get a left-border accent + lighter text when active (replacing the
current flat `bg-surface` active state). Structure (routes, admin-gating logic) is unchanged —
this is a visual-only pass on an existing, working component.

Page content area keeps the existing `Layout.tsx` flex structure (sidebar + `<Outlet>`); only the
Tailwind classes/tokens change, not the component tree.

### 3. The phase-grouped timeline (signature component)

Rewrites `StepTimeline.tsx` (already once-redesigned, now gets the Archive treatment and a real
grouping structure) to organize entries by pipeline phase instead of one flat list, per the
approved "grouped by phase, steps nested" decision:

- **Phase row**: a status dot (olive = done, terracotta pulsing = live, empty/outlined = pending)
  + phase name (serif, semibold) + a trailing summary (`"4 steps · 0.8s"` once done, `"running…"`
  while live, nothing while pending — pending phase name renders in `--color-text-pending`).
- **Steps nested under the live phase only**: a `✓`/`◐` tick + node's human name (e.g. "second
  opinion") + the raw node id in small mono (e.g. `classification_second_opinion`) for anyone who
  needs to cross-reference logs/audit records. Completed phases collapse to just the summary line
  (no need to re-show 4 already-done step rows) — this is what keeps the "full step-by-step
  history" requirement from turning into visual noise once the phase itself is done. The full
  step list for a completed phase is still available (see Document Detail's Audit tab in
  Decision 5) — collapsing here is about what's useful to see *while a job is still running*, not
  about hiding data.
- **A thin progress bar** at the bottom of the card, terracotta fill proportional to phases
  completed (4 phases: ingesta/enrichment/classification/routing → 25% per phase). A simple,
  low-effort way to give an at-a-glance sense of "how far along" without needing to read the whole
  timeline — validated in the full-page mockup.

The four phase groups map onto the existing `TimelineEntry.node` values via a prefix/name lookup
(`node1_file_reception`..`node4_duplicate_control` → Ingesta; `enrichment_*` → Enrichment;
`classification_*` → Classification; `classification_routing` → Routing) — no backend schema
change needed; this is a pure frontend grouping function over data the `GET /jobs/{id}/timeline`
endpoint and the `/pipeline/{id}/events` SSE stream already provide.

### 4. Processing page

Restructured into "Queued" (compact one-line rows — filename + a muted "waiting for a worker"
note) and "Processing" (full job cards using the Decision 3 timeline) sections, matching the
validated full-page mockup. Section labels in small-caps mono
(`QUEUED — 1` / `PROCESSING — 1`), consistent with the timestamp/ID mono treatment elsewhere.

No change to the polling/SSE data-fetching logic in `ProcessingPage.tsx`/`fetchRunningJobs`/
`fetchJobTimeline` — this is a visual layer on top of already-working data flow (including the
just-shipped backend fix that keeps a job's `Job.status` at `"processing"` through the whole
pipeline, which is what makes this page show anything at all during enrichment/classification).

### 5. Classification page & Document Detail page

**Classification table** (`DataTable.tsx`, `ClassificationPage.tsx`): restyled with the Archive
palette — serif for filenames/labels, mono for confidence scores and dates, badges recolored
(`accept` → olive-tinted, `human_review` → amber-tinted, matching `--color-success`/
`--color-warning`). Filter inputs restyled to match. No change to filtering/query logic.

**Document Detail page** (`DocumentDetailPage.tsx`): the two "dump raw JSON in a `<pre>` tag" tabs
(Enrichment, Classification) are replaced with real key/value layouts — a `<dl>`-style grid
(label in small mono, value in serif) for classification's label/confidence/review-route/second-
opinion fields, a confidence value rendered as a small horizontal bar + number (not just a raw
float), and smell flags as small pill tags instead of a raw JSON array. The Extraction tab keeps
rendering raw text (that's genuinely raw document text, not structured data — a `<pre>` block
stays correct there) but gets serif type instead of the default monospace `<pre>` styling for
readability. The **Audit tab** is restructured to use the Decision 3 timeline component in its
full (non-collapsed, all-phases-expanded) form — since this is a finished job being reviewed after
the fact, there's no "live phase" to keep other phases collapsed for for; showing the complete
step-by-step history here is exactly the "full detail on demand" half of the signature timeline's
job, matching how the same component condenses on Processing but expands here.

Tabs themselves restyled: bottom-border-on-active instead of the current filled-background-when-
active treatment, matching the validated mockup.

The PDF pane and `PdfViewer.tsx` component are **not touched by this spec** — that component was
just fixed (auth, CSS, memoization) this session and works correctly; restyling its surrounding
container padding/border to match the new tokens is in scope, but no logic changes.

### 6. Users & Audit Log pages (admin)

Same full Archive treatment as Classification — same table styles, badges, mono labels. No
separate lighter/denser variant (explicit user choice) — one consistent visual language across
every list/table in the app rather than two table styles to maintain.

### 7. Motion

Two things, deliberately minimal (per the "distinctive but restrained" direction, and explicit
user choice of "a bit more — smooth section reveals" over both a bare pulse-only option and a
heavier animation approach):

- **Live-step pulse**: the terracotta dot on the currently-running phase/step gets a subtle
  `animate-pulse` (already used in the current `StepTimeline.tsx` and carried forward) — the only
  continuously-repeating animation in the app.
- **Section reveal**: when a phase transitions from pending → live, or live → done (i.e. the
  SSE stream delivers a new `NodeEvent` that changes a phase's status), the newly-revealed content
  (a phase's summary line appearing, or its steps collapsing) gets a short (150-200ms) fade/height
  transition rather than popping in instantly. Implemented with CSS transitions on the existing
  conditional-render already driving `StepTimeline`, not a new animation library — Tailwind's
  built-in `transition`/`duration-150` utilities are sufficient, no new dependency.

No page-transition animation (route changes render instantly, as today) — that's a heavier
addition than what was asked for, and this app's navigation is a persistent sidebar + swapped
`<Outlet>` content, not the kind of full-page transition this treatment would suit.

## Non-Goals

- **No backend changes.** Every decision above operates on data endpoints that already exist
  (`GET /pipeline/jobs`, `GET /pipeline/jobs/{id}/timeline`, `GET /pipeline/{id}/events` SSE,
  `GET /documents/{id}/detail`, `GET /users`, `GET /audit`). This is a pure frontend visual/
  structural pass.
- **No Chat page redesign.** It's an explicit placeholder for future Stage 5 (Knowledge Base +
  Chat Agent, not yet built) — restyling a stub with no real content ahead of that feature's own
  design pass would be wasted, throwaway work. It only gets the shared shell treatment (sidebar/
  layout tokens) for free from Decision 2, nothing page-specific. Any real chat UI (message list,
  a form to send messages) belongs to that page's own future design pass, not this one.
- **No condensed timeline in the Classification table.** Decision 3 mentions this as a possible
  future reuse of the signature component, but the Classification table itself (Decision 5) only
  needs its existing badge/label columns restyled — adding a mini-timeline column is new scope,
  not part of making the current columns look right.
- **No new component library or CSS framework.** Stays on Tailwind v4 utility classes + the
  `src/index.css` token system, consistent with the existing codebase's approach — no styled-
  components, no Radix/shadcn adoption, nothing that would require new dependencies.
- **No light-mode variant.** The whole app is dark-theme-only today (an explicit earlier decision,
  not revisited here); Archive's warm-dark palette replaces the existing dark palette, it doesn't
  add a second theme.

## Testing

Existing Vitest component tests (`StepTimeline.test.tsx`, `RequireAdmin.test.tsx`,
`ReclassifyPanel.test.tsx`, etc.) assert behavior and rendered text content, not exact CSS classes
— they should continue passing unchanged through a visual-only restyle. Where a test does assert
a specific Tailwind class (if any exist), those get updated to match the new token names as part
of implementation, not left stale.

No new test infrastructure needed — this is a styling/structure pass on already-tested data flows,
not new logic.

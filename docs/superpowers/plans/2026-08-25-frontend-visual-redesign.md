# Frontend Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the "Archive" visual direction (warm paper palette, serif type, terracotta/olive
accents) across the whole Classiflow frontend, and rework `StepTimeline` into a phase-grouped
signature component reused on both the Processing page (condensed, live) and the Document Detail
page's Audit tab (fully expanded, historical).

**Architecture:** Pure frontend visual/structural pass — no backend changes, no new dependencies.
Token swap in `src/index.css` cascades through every component via existing `var(--color-*)`
Tailwind arbitrary-value classes (already the codebase's pattern). `StepTimeline` gains a
phase-grouping function and two render modes (condensed/expanded) via a new prop, keeping its
existing `TimelineEntry[]` input contract so callers don't need shape changes beyond one new prop.

**Tech Stack:** React 19, TypeScript, Vite 6, Tailwind v4 (CSS variables in `src/index.css`),
Vitest + Testing Library (existing test setup, no new tooling).

**Spec:** `docs/superpowers/specs/2026-08-25-frontend-visual-redesign-design.md`

## Global Constraints

- No backend changes — every task operates on data already returned by existing endpoints.
- No new npm dependencies — Tailwind v4 utilities only (including `transition`/`duration-150` for
  motion), no animation library, no component library.
- No webfonts — `Georgia, 'Times New Roman', serif` and `'Courier New', ui-monospace, monospace`
  are both system font stacks already available; no `<link>`/`@import` additions to `index.html`
  or `index.css`.
- No light-mode variant — the app stays dark-theme-only; Archive's palette *replaces* the existing
  dark tokens rather than adding a second theme.
- Exact color values (copied verbatim from the spec's Decision 1) — every task below uses these,
  never an approximated or freehand hex:
  ```css
  --color-bg: #14110f;
  --color-bg-inset: #100d0a;
  --color-surface: #1b1712;
  --color-surface-hover: #221d16;
  --color-border: #322a20;
  --color-border-subtle: #2a2319;
  --color-text: #f2ead9;
  --color-text-muted: #a89a80;
  --color-text-faint: #6b5f4d;
  --color-text-pending: #57503f;
  --color-accent: #c1663a;
  --color-success: #6b8f5a;
  --color-warning: #d49d3c;
  --color-danger: #b5453a;
  ```
- Non-Goals from the spec — do not implement these: Chat page redesign, a condensed timeline
  column in the Classification table, any new CSS framework/component library, a light-mode
  variant.

---

### Task 1: Token system — `src/index.css`

**Files:**
- Modify: `src/classiflow/frontend/src/index.css`

**Interfaces:**
- Consumes: nothing (this is the root token definition).
- Produces: the 14 CSS custom properties listed in Global Constraints above, replacing the
  existing 9 (`--color-bg`, `--color-surface`, `--color-border`, `--color-text`,
  `--color-text-muted`, `--color-accent`, `--color-success`, `--color-warning`, `--color-danger`).
  Every later task's `var(--color-*)` references resolve against these. Also produces two `body`-
  level font-family declarations that every page inherits.

- [ ] **Step 1: Replace the `:root` token block**

Open `src/classiflow/frontend/src/index.css`. Replace the entire `:root { ... }` block (currently
lines 3-13) with:

```css
:root {
  /* Backgrounds */
  --color-bg: #14110f;
  --color-bg-inset: #100d0a;
  --color-surface: #1b1712;
  --color-surface-hover: #221d16;

  /* Borders */
  --color-border: #322a20;
  --color-border-subtle: #2a2319;

  /* Text */
  --color-text: #f2ead9;
  --color-text-muted: #a89a80;
  --color-text-faint: #6b5f4d;
  --color-text-pending: #57503f;

  /* Accents */
  --color-accent: #c1663a;
  --color-success: #6b8f5a;
  --color-warning: #d49d3c;
  --color-danger: #b5453a;

  /* Type */
  --font-serif: Georgia, "Times New Roman", serif;
  --font-mono: "Courier New", ui-monospace, monospace;
}
```

- [ ] **Step 2: Apply the serif body font**

In the same file, update the `body` rule (currently just `margin`/`background`/`color`) to also
set `font-family: var(--font-serif);`:

```css
body {
  margin: 0;
  background: var(--color-bg);
  color: var(--color-text);
  font-family: var(--font-serif);
}
```

- [ ] **Step 3: Manual visual check**

Run: hand this to the user — `npm run dev` (from `src/classiflow/frontend/`) — and confirm the
page background is now warm dark brown (`#14110f`) instead of the old cool `#0f1115`, and body
text renders in a serif face. No automated test for a pure CSS token change; this is a visual
sanity check before building on top of it.

- [ ] **Step 4: Run typecheck and lint**

Hand to the user: `npx tsc -b && npm run lint` (from `src/classiflow/frontend/`).
Expected: both clean — a CSS-only change touches no TypeScript.

- [ ] **Step 5: Commit**

```bash
git add src/classiflow/frontend/src/index.css
git commit -m "style: replace dark palette with Archive warm-paper token system"
```

---

### Task 2: Sidebar restyle

**Files:**
- Modify: `src/classiflow/frontend/src/components/Sidebar.tsx`

**Interfaces:**
- Consumes: `useAuth()` from `../auth/AuthContext` (unchanged — `isAdmin`, `logout`), `NavLink`
  from `react-router` (unchanged).
- Produces: no new exports; same default export, same rendered nav structure/routes. Visual-only
  change, no prop or behavior change, so nothing downstream needs updating.

- [ ] **Step 1: Read the existing test surface**

There is no `Sidebar.test.tsx` in the codebase today (confirmed by inspection) — this component is
only covered indirectly through pages that render it inside `Layout`. No test file to update in
this task; skip to the implementation step. (If this assumption is wrong when you run the suite,
stop and check — do not silently add a new test file that duplicates untested behavior.)

- [ ] **Step 2: Restyle the sidebar shell and wordmark**

Replace the full contents of `src/classiflow/frontend/src/components/Sidebar.tsx`:

```tsx
import { NavLink } from "react-router";
import { useAuth } from "../auth/AuthContext";

const LINK_CLASS = "block rounded-md px-3 py-2 text-sm border-l-2 border-transparent";
const ACTIVE_CLASS = "border-[var(--color-accent)] bg-[var(--color-surface)] text-[var(--color-text)]";
const INACTIVE_CLASS = "text-[var(--color-text-muted)] hover:text-[var(--color-text)]";

function linkClass({ isActive }: { isActive: boolean }): string {
  return `${LINK_CLASS} ${isActive ? ACTIVE_CLASS : INACTIVE_CLASS}`;
}

export default function Sidebar() {
  const { isAdmin, logout } = useAuth();

  return (
    <nav className="flex h-screen w-56 flex-col justify-between border-r border-[var(--color-border)] bg-[var(--color-bg-inset)] p-4">
      <div className="flex flex-col gap-1">
        <p className="mb-4 px-3 text-lg font-bold text-[var(--color-accent)]">Classiflow</p>
        <NavLink to="/" end className={linkClass}>
          Processing
        </NavLink>
        <NavLink to="/classification" className={linkClass}>
          Classification
        </NavLink>
        <NavLink to="/chat" className={linkClass}>
          Chat
        </NavLink>
        {isAdmin && (
          <>
            <NavLink to="/users" className={linkClass}>
              Users
            </NavLink>
            <NavLink to="/audit" className={linkClass}>
              Audit Log
            </NavLink>
          </>
        )}
      </div>
      <button onClick={logout} className={`${LINK_CLASS} ${INACTIVE_CLASS} text-left`}>
        Sign out
      </button>
    </nav>
  );
}
```

- [ ] **Step 3: Manual visual check**

Hand to the user: with `npm run dev` still running, reload and confirm the sidebar now has the
dark-inset background, terracotta "Classiflow" wordmark, and a left-border accent on the active
nav item instead of the old flat background highlight.

- [ ] **Step 4: Run typecheck, lint, and existing tests**

Hand to the user: `npx tsc -b && npm run lint && npm run test` (from `src/classiflow/frontend/`).
Expected: all clean — no test references `Sidebar`'s old class strings directly (confirmed in
Step 1), so nothing should break.

- [ ] **Step 5: Commit**

```bash
git add src/classiflow/frontend/src/components/Sidebar.tsx
git commit -m "style: restyle Sidebar with Archive tokens and accent wordmark"
```

---

### Task 3: Phase-grouping logic for `StepTimeline`

**Files:**
- Create: `src/classiflow/frontend/src/components/timelinePhases.ts`
- Test: `src/classiflow/frontend/src/components/timelinePhases.test.ts`

**Interfaces:**
- Consumes: `TimelineEntry` from `../api/jobs` (existing type — `node: string`, `status: string`,
  `passed: boolean | null`, `detail: Record<string, unknown> | null`, `timestamp: string`,
  `durationMs: number | null`).
- Produces:
  ```typescript
  export type PhaseName = "Ingesta" | "Enrichment" | "Classification" | "Routing";
  export interface Phase {
    name: PhaseName;
    entries: TimelineEntry[];
  }
  export function groupByPhase(entries: TimelineEntry[]): Phase[];
  ```
  `groupByPhase` is consumed by Task 4 (`StepTimeline` rewrite). It returns phases **in a fixed
  order** (`Ingesta`, `Enrichment`, `Classification`, `Routing`) and **only includes a phase if at
  least one entry maps to it** — a rejected-at-node2 job never produces `Enrichment`/
  `Classification`/`Routing` phase objects, matching how `TimelineEntry` data itself only contains
  entries for nodes that actually ran (see the existing `StepTimeline.tsx` comment about no fixed
  upfront node sequence).

- [ ] **Step 1: Write the failing tests**

Create `src/classiflow/frontend/src/components/timelinePhases.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { groupByPhase } from "./timelinePhases";
import type { TimelineEntry } from "../api/jobs";

function entry(node: string, status = "passed"): TimelineEntry {
  return {
    node,
    status,
    passed: status === "passed" ? true : status === "failed" ? false : null,
    detail: null,
    timestamp: "2026-08-25T10:00:00Z",
    durationMs: 50,
  };
}

describe("groupByPhase", () => {
  it("groups ingesta nodes (node1-node4) under Ingesta", () => {
    const phases = groupByPhase([
      entry("node1_file_reception"),
      entry("node2_format_validation"),
      entry("node3_content_validation"),
      entry("node4_duplicate_control"),
    ]);
    expect(phases).toHaveLength(1);
    expect(phases[0].name).toBe("Ingesta");
    expect(phases[0].entries).toHaveLength(4);
  });

  it("groups enrichment_* nodes under Enrichment", () => {
    const phases = groupByPhase([
      entry("enrichment_text_cleaner"),
      entry("enrichment_entity_extractor"),
    ]);
    expect(phases).toHaveLength(1);
    expect(phases[0].name).toBe("Enrichment");
  });

  it("groups classification_* nodes (except routing) under Classification", () => {
    const phases = groupByPhase([
      entry("classification_primary_classifier"),
      entry("classification_second_opinion"),
      entry("classification_llm_judge"),
    ]);
    expect(phases).toHaveLength(1);
    expect(phases[0].name).toBe("Classification");
  });

  it("puts classification_routing under its own Routing phase, not Classification", () => {
    const phases = groupByPhase([
      entry("classification_primary_classifier"),
      entry("classification_routing"),
    ]);
    expect(phases).toHaveLength(2);
    expect(phases[0].name).toBe("Classification");
    expect(phases[0].entries).toHaveLength(1);
    expect(phases[1].name).toBe("Routing");
    expect(phases[1].entries).toHaveLength(1);
  });

  it("returns phases in fixed Ingesta/Enrichment/Classification/Routing order regardless of input order", () => {
    const phases = groupByPhase([
      entry("classification_routing"),
      entry("node1_file_reception"),
      entry("enrichment_text_cleaner"),
    ]);
    expect(phases.map((p) => p.name)).toEqual(["Ingesta", "Enrichment", "Routing"]);
  });

  it("omits a phase entirely when no entry maps to it", () => {
    const phases = groupByPhase([entry("node1_file_reception"), entry("node2_format_validation", "failed")]);
    expect(phases).toHaveLength(1);
    expect(phases[0].name).toBe("Ingesta");
  });

  it("returns an empty array for no entries", () => {
    expect(groupByPhase([])).toEqual([]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Hand to the user: `npm run test -- timelinePhases` (from `src/classiflow/frontend/`).
Expected: FAIL — `Cannot find module './timelinePhases'` or similar (file doesn't exist yet).

- [ ] **Step 3: Implement `groupByPhase`**

Create `src/classiflow/frontend/src/components/timelinePhases.ts`:

```typescript
import type { TimelineEntry } from "../api/jobs";

export type PhaseName = "Ingesta" | "Enrichment" | "Classification" | "Routing";

export interface Phase {
  name: PhaseName;
  entries: TimelineEntry[];
}

const PHASE_ORDER: PhaseName[] = ["Ingesta", "Enrichment", "Classification", "Routing"];

function phaseFor(node: string): PhaseName {
  if (node === "classification_routing") {
    return "Routing";
  }
  if (node.startsWith("classification_")) {
    return "Classification";
  }
  if (node.startsWith("enrichment_")) {
    return "Enrichment";
  }
  // node1_file_reception..node4_duplicate_control, and the extraction step
  // (unprefixed "extraction") all belong to Stage 1 ingesta.
  return "Ingesta";
}

export function groupByPhase(entries: TimelineEntry[]): Phase[] {
  const byPhase = new Map<PhaseName, TimelineEntry[]>();
  for (const entry of entries) {
    const name = phaseFor(entry.node);
    const bucket = byPhase.get(name) ?? [];
    bucket.push(entry);
    byPhase.set(name, bucket);
  }
  return PHASE_ORDER.filter((name) => byPhase.has(name)).map((name) => ({
    name,
    entries: byPhase.get(name)!,
  }));
}
```

- [ ] **Step 4: Run tests to verify they pass**

Hand to the user: `npm run test -- timelinePhases`.
Expected: PASS — all 7 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/classiflow/frontend/src/components/timelinePhases.ts src/classiflow/frontend/src/components/timelinePhases.test.ts
git commit -m "feat: add phase-grouping logic for the pipeline timeline"
```

---

### Task 4: Rewrite `StepTimeline` — phase-grouped, condensed/expanded modes

**Files:**
- Modify: `src/classiflow/frontend/src/components/StepTimeline.tsx`
- Modify: `src/classiflow/frontend/src/components/StepTimeline.test.tsx`

**Interfaces:**
- Consumes: `Phase`/`groupByPhase` from `./timelinePhases` (Task 3), `TimelineEntry` from
  `../api/jobs` (existing).
- Produces:
  ```typescript
  export default function StepTimeline(props: {
    entries: TimelineEntry[];
    mode?: "condensed" | "expanded"; // default "condensed"
  }): JSX.Element;
  ```
  `mode` is new — Task 5 (ProcessingPage) uses the default `"condensed"` (omits the prop), Task 7
  (DocumentDetailPage Audit tab) passes `mode="expanded"`. The existing `entries` prop and its
  `TimelineEntry` shape are unchanged, so this is a backward-compatible addition, not a breaking
  change to the one existing caller (`ProcessingPage.tsx`, updated in Task 5 anyway).

- [ ] **Step 1: Write the new/updated failing tests**

Replace the full contents of `src/classiflow/frontend/src/components/StepTimeline.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StepTimeline from "./StepTimeline";
import type { TimelineEntry } from "../api/jobs";

function entry(node: string, status: string, timestamp: string): TimelineEntry {
  return {
    node,
    status,
    passed: status === "passed" ? true : status === "failed" ? false : null,
    detail: null,
    timestamp,
    durationMs: status === "passed" ? 50 : null,
  };
}

const INGESTA_DONE: TimelineEntry[] = [
  entry("node1_file_reception", "passed", "2026-08-24T10:00:00Z"),
  entry("node2_format_validation", "passed", "2026-08-24T10:00:01Z"),
];

describe("StepTimeline", () => {
  it("shows a waiting message when there are no entries yet", () => {
    render(<StepTimeline entries={[]} />);
    expect(screen.getByText("Waiting for the first step…")).toBeInTheDocument();
  });

  it("renders a phase name for a completed phase", () => {
    render(<StepTimeline entries={INGESTA_DONE} />);
    expect(screen.getByText("Ingesta")).toBeInTheDocument();
  });

  it("condensed mode: collapses a completed phase to a summary, hiding its individual step names", () => {
    render(<StepTimeline entries={INGESTA_DONE} mode="condensed" />);
    expect(screen.getByText("Ingesta")).toBeInTheDocument();
    expect(screen.queryByText("node1_file_reception")).not.toBeInTheDocument();
    expect(screen.queryByText("node2_format_validation")).not.toBeInTheDocument();
  });

  it("condensed mode: expands the live (non-terminal) phase to show its individual steps", () => {
    const entries: TimelineEntry[] = [
      ...INGESTA_DONE,
      entry("classification_primary_classifier", "passed", "2026-08-24T10:00:02Z"),
      entry("classification_second_opinion", "started", "2026-08-24T10:00:03Z"),
    ];
    render(<StepTimeline entries={entries} mode="condensed" />);
    expect(screen.getByText("Classification")).toBeInTheDocument();
    expect(screen.getByText("classification_second_opinion")).toBeInTheDocument();
    expect(screen.getByText("started…")).toBeInTheDocument();
    // The already-done sibling phase stays collapsed:
    expect(screen.queryByText("node1_file_reception")).not.toBeInTheDocument();
  });

  it("expanded mode: shows every phase's individual steps, including completed ones", () => {
    render(<StepTimeline entries={INGESTA_DONE} mode="expanded" />);
    expect(screen.getByText("node1_file_reception")).toBeInTheDocument();
    expect(screen.getByText("node2_format_validation")).toBeInTheDocument();
  });

  it("defaults to condensed mode when mode is omitted", () => {
    render(<StepTimeline entries={INGESTA_DONE} />);
    expect(screen.queryByText("node1_file_reception")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Hand to the user: `npm run test -- StepTimeline`.
Expected: FAIL — the current `StepTimeline` has no phase grouping and no `mode` prop, so the new
assertions (`getByText("Ingesta")`, condensed/expanded distinctions) don't match rendered output.

- [ ] **Step 3: Implement the phase-grouped `StepTimeline`**

Replace the full contents of `src/classiflow/frontend/src/components/StepTimeline.tsx`:

```tsx
import type { TimelineEntry } from "../api/jobs";
import { groupByPhase, type Phase } from "./timelinePhases";

const STATUS_DOT: Record<string, string> = {
  passed: "bg-[var(--color-success)]",
  failed: "bg-[var(--color-danger)]",
  started: "bg-[var(--color-accent)]",
  processing: "bg-[var(--color-accent)]",
};

const TERMINAL_STATUSES = new Set(["passed", "failed"]);

function formatNodeName(node: string): string {
  return node
    .replace(/^node\d+_/, "")
    .replace(/^(enrichment|classification)_/, "")
    .split("_")
    .join(" ");
}

function isPhaseLive(phase: Phase): boolean {
  const last = phase.entries[phase.entries.length - 1];
  return !TERMINAL_STATUSES.has(last.status);
}

function StepRow({ entry, live }: { entry: TimelineEntry; live: boolean }) {
  return (
    <div className="relative flex items-center gap-2.5 py-0.5 transition-all duration-150">
      <span
        className={`absolute -left-[21px] h-1.5 w-1.5 rounded-full ${live ? "animate-pulse " : ""}${STATUS_DOT[entry.status] ?? "bg-[var(--color-text-muted)]"}`}
      />
      <span
        className={`text-sm ${live ? "font-semibold text-[var(--color-text)]" : "text-[var(--color-text-muted)]"}`}
      >
        {formatNodeName(entry.node)}
      </span>
      <span className="font-mono text-[11px] text-[var(--color-text-faint)]">{entry.node}</span>
    </div>
  );
}

function PhaseGroup({
  phase,
  expanded,
}: {
  phase: Phase;
  expanded: boolean;
}) {
  const live = isPhaseLive(phase);
  const dotClass = live
    ? "animate-pulse bg-[var(--color-accent)]"
    : phase.entries.every((e) => e.status === "passed")
      ? "bg-[var(--color-success)]"
      : "bg-[var(--color-danger)]";

  // Condensed mode only expands the phase currently in progress; a phase that's
  // already terminal (done or failed) collapses to its summary line so a
  // multi-minute job doesn't turn into a wall of already-known-good steps.
  const showSteps = expanded || live;

  return (
    <div className="transition-all duration-150">
      <div className="relative flex items-center gap-2.5">
        <span className={`absolute -left-[21px] h-1.5 w-1.5 rounded-full ${dotClass}`} />
        <span className="text-sm font-semibold text-[var(--color-text)]">{phase.name}</span>
        {!showSteps && (
          <span className="font-mono text-[11px] text-[var(--color-text-faint)]">
            {phase.entries.length} step{phase.entries.length === 1 ? "" : "s"}
          </span>
        )}
        {live && <span className="text-sm text-[var(--color-text-muted)]">running…</span>}
      </div>
      {showSteps && (
        <div className="ml-4 flex flex-col gap-1 pt-1">
          {phase.entries.map((entry, i) => (
            <StepRow
              key={`${entry.node}-${entry.timestamp}-${i}`}
              entry={entry}
              live={live && i === phase.entries.length - 1 && !TERMINAL_STATUSES.has(entry.status)}
            />
          ))}
          {live && (
            <p className="pl-0 text-sm text-[var(--color-text-muted)]">
              {phase.entries[phase.entries.length - 1].status}…
            </p>
          )}
        </div>
      )}
    </div>
  );
}

const ALL_PHASE_NAMES = ["Ingesta", "Enrichment", "Classification", "Routing"] as const;

export default function StepTimeline({
  entries,
  mode = "condensed",
}: {
  entries: TimelineEntry[];
  mode?: "condensed" | "expanded";
}) {
  if (entries.length === 0) {
    return <p className="text-sm text-[var(--color-text-muted)]">Waiting for the first step…</p>;
  }

  const phases = groupByPhase(entries);
  const doneCount = phases.filter((p) => !isPhaseLive(p)).length;
  const progressPct = Math.round((doneCount / ALL_PHASE_NAMES.length) * 100);

  return (
    <div className="flex flex-col gap-3">
      <div className="relative flex flex-col gap-3 border-l border-[var(--color-border-subtle)] pl-4">
        {phases.map((phase) => (
          <PhaseGroup key={phase.name} phase={phase} expanded={mode === "expanded"} />
        ))}
      </div>
      {mode === "condensed" && (
        <div className="h-[3px] overflow-hidden rounded-full bg-[var(--color-border-subtle)]">
          <div
            className="h-full bg-[var(--color-accent)] transition-all duration-200"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Hand to the user: `npm run test -- StepTimeline`.
Expected: PASS — all 6 tests green.

- [ ] **Step 5: Manual visual check**

Hand to the user: with the dev server running and a job mid-pipeline (see Task 5's manual check
for how to get one), confirm the Processing page's card shows collapsed "Ingesta · 4 steps" /
"Enrichment · 3 steps" lines with the currently-running phase expanded underneath, plus the
terracotta progress bar at the bottom.

- [ ] **Step 6: Commit**

```bash
git add src/classiflow/frontend/src/components/StepTimeline.tsx src/classiflow/frontend/src/components/StepTimeline.test.tsx
git commit -m "feat: rewrite StepTimeline as a phase-grouped condensed/expanded component"
```

---

### Task 5: Processing page — Queued/Processing sections restyle

**Files:**
- Modify: `src/classiflow/frontend/src/pages/ProcessingPage.tsx`

**Interfaces:**
- Consumes: `fetchRunningJobs`, `fetchJobTimeline`, `JobSummary`, `TimelineEntry` from `../api/jobs`
  (all unchanged), `StepTimeline` from `../components/StepTimeline` (Task 4 — called without
  `mode`, so it defaults to `"condensed"`).
- Produces: no new exports; same default export. No prop/behavior change for anything downstream.

- [ ] **Step 1: Confirm no existing test targets this page**

There is no `ProcessingPage.test.tsx` in the codebase (confirmed by inspection — this page's data
flow is exercised only manually / through the backend's own test suite). No test file to update;
proceed directly to the restyle.

- [ ] **Step 2: Restyle the page shell and sections**

Replace the full contents of `src/classiflow/frontend/src/pages/ProcessingPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchRunningJobs,
  fetchJobTimeline,
  type JobSummary,
  type TimelineEntry,
} from "../api/jobs";
import StepTimeline from "../components/StepTimeline";

// ponytail: 2s polling misses very fast jobs less often than the original 10s, but a
// job that completes in under 2s can still slip through entirely -- an SSE-driven
// "job appeared" signal (independent of polling) would close that gap fully if it
// ever matters; not built here since there's no upload UI yet to make it observable.
const REFETCH_INTERVAL_MS = 2_000;

function JobCard({ job }: { job: JobSummary }) {
  const [entries, setEntries] = useState<TimelineEntry[]>([]);

  useEffect(() => {
    let cancelled = false;

    fetchJobTimeline(job.jobId)
      .then((backfilled) => {
        if (!cancelled) {
          setEntries(backfilled);
        }
      })
      .catch(() => {});

    const source = new EventSource(`/pipeline/${job.jobId}/events`);
    source.addEventListener("node_update", (event) => {
      const payload = JSON.parse((event as MessageEvent<string>).data) as {
        node: string;
        status: string;
        timestamp: string;
      };
      setEntries((prev) => [
        ...prev,
        {
          node: payload.node,
          status: payload.status,
          passed: null,
          detail: null,
          timestamp: payload.timestamp,
          durationMs: null,
        },
      ]);
    });

    return () => {
      cancelled = true;
      source.close();
    };
  }, [job.jobId]);

  return (
    <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-4 transition-all duration-150">
      <p className="font-semibold text-[var(--color-text)]">{job.filename}</p>
      <p className="mb-4 font-mono text-xs text-[var(--color-text-faint)]">{job.jobId}</p>
      <StepTimeline entries={entries} />
    </div>
  );
}

export default function ProcessingPage() {
  const { data: jobs = [] } = useQuery({
    queryKey: ["running-jobs"],
    queryFn: fetchRunningJobs,
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const queued = jobs.filter((j) => j.status === "queued");
  const processing = jobs.filter((j) => j.status === "processing");

  return (
    <div className="p-6">
      <h1 className="mb-6 text-xl font-bold text-[var(--color-text)]">Processing</h1>

      <p className="mb-2 font-mono text-[11px] uppercase tracking-wider text-[var(--color-text-faint)]">
        Queued — {queued.length}
      </p>
      <div className="mb-8 flex flex-col gap-2">
        {queued.map((job) => (
          <div
            key={job.jobId}
            className="flex items-center justify-between rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
          >
            <span className="text-[var(--color-text)]">{job.filename}</span>
            <span className="text-[var(--color-text-faint)]">waiting for a worker</span>
          </div>
        ))}
        {queued.length === 0 && (
          <p className="text-sm text-[var(--color-text-muted)]">None</p>
        )}
      </div>

      <p className="mb-2 font-mono text-[11px] uppercase tracking-wider text-[var(--color-text-faint)]">
        Processing — {processing.length}
      </p>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {processing.map((job) => (
          <JobCard key={job.jobId} job={job} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Manual verification against a real job**

Hand to the user: with the backend running (`uv run python -m classiflow`) and the frontend dev
server up, upload a document and confirm on the Processing page: (a) it appears under "Processing"
and stays there through enrichment/classification (the backend `Job.status` fix from earlier this
session is what makes this possible), (b) the phase-grouped timeline updates live as phases
complete, (c) the progress bar advances, (d) once fully done the job disappears from this page
(it's no longer `queued`/`processing`).

- [ ] **Step 4: Run typecheck, lint, and tests**

Hand to the user: `npx tsc -b && npm run lint && npm run test` (from `src/classiflow/frontend/`).
Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add src/classiflow/frontend/src/pages/ProcessingPage.tsx
git commit -m "style: restyle ProcessingPage with Archive tokens and phase timeline"
```

---

### Task 6: Classification page, `DataTable`, and `StatusBadge` restyle

**Files:**
- Modify: `src/classiflow/frontend/src/components/DataTable.tsx`
- Modify: `src/classiflow/frontend/src/components/StatusBadge.tsx`
- Modify: `src/classiflow/frontend/src/pages/ClassificationPage.tsx`

**Interfaces:**
- Consumes: no interface changes — `DataTable<T>`'s generic `Column<T>`/`rowKey`/`onRowClick`
  props, and `StatusBadge`'s `{ status: string }` prop, are unchanged. `fetchJobsPage`,
  `ClassificationSummary` from `../api/documents` unchanged.
- Produces: no new exports. Visual-only.

- [ ] **Step 1: Confirm no test targets these files' styling**

No `DataTable.test.tsx`, `StatusBadge.test.tsx`, or `ClassificationPage.test.tsx` exist in the
codebase (confirmed by inspection). Proceed directly to the restyle; no test changes in this task.

- [ ] **Step 2: Restyle `DataTable`**

Replace the full contents of `src/classiflow/frontend/src/components/DataTable.tsx`:

```tsx
import type { ReactNode } from "react";

export interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
}

export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
}) {
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-[var(--color-border)] text-left">
          {columns.map((col) => (
            <th
              key={col.header}
              className="p-3 font-mono text-[10.5px] uppercase tracking-wider text-[var(--color-text-faint)]"
            >
              {col.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={rowKey(row)}
            onClick={() => onRowClick?.(row)}
            className={`border-b border-[var(--color-border-subtle)] text-[var(--color-text)] transition-colors duration-150 ${onRowClick ? "cursor-pointer hover:bg-[var(--color-surface)]" : ""}`}
          >
            {columns.map((col) => (
              <td key={col.header} className="p-3">
                {col.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 3: Restyle `StatusBadge`**

Replace the full contents of `src/classiflow/frontend/src/components/StatusBadge.tsx`:

```tsx
const COLORS: Record<string, string> = {
  accept: "bg-[var(--color-success)]/20 text-[var(--color-success)]",
  human_review: "bg-[var(--color-warning)]/20 text-[var(--color-warning)]",
  llm_judge: "bg-[var(--color-accent)]/20 text-[var(--color-accent)]",
};

export default function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`rounded-full px-2.5 py-0.5 font-mono text-[11px] font-semibold ${COLORS[status] ?? "bg-[var(--color-text-muted)]/20 text-[var(--color-text-muted)]"}`}
    >
      {status}
    </span>
  );
}
```

Note: this switches from solid-fill badges with black text to tinted (20%-opacity background,
full-opacity colored text) badges, matching the validated mockup's `arch-badge` treatment — solid
fills in the old bright success/warning/accent colors would clash against the new warm-dark
surface, tinted badges sit correctly on `--color-surface`.

- [ ] **Step 4: Restyle `ClassificationPage`**

Replace the full contents of `src/classiflow/frontend/src/pages/ClassificationPage.tsx`:

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { fetchJobsPage, type ClassificationSummary } from "../api/documents";
import DataTable, { type Column } from "../components/DataTable";
import StatusBadge from "../components/StatusBadge";

const COLUMNS: Column<ClassificationSummary>[] = [
  { header: "Filename", render: (row) => row.filename },
  { header: "Label", render: (row) => row.label ?? "—" },
  { header: "Review Route", render: (row) => <StatusBadge status={row.reviewRoute} /> },
  {
    header: "Confidence",
    render: (row) => <span className="font-mono text-[var(--color-text-muted)]">{row.confidence.toFixed(2)}</span>,
  },
  { header: "Judged", render: (row) => (row.judgedByLlm ? "Yes" : "No") },
  {
    header: "Created",
    render: (row) => (
      <span className="font-mono text-xs text-[var(--color-text-faint)]">
        {new Date(row.createdAt).toLocaleString()}
      </span>
    ),
  },
];

export default function ClassificationPage() {
  const [label, setLabel] = useState("");
  const [reviewRoute, setReviewRoute] = useState("");
  const navigate = useNavigate();

  const { data } = useQuery({
    queryKey: ["jobs", label, reviewRoute],
    queryFn: () =>
      fetchJobsPage({ label: label || undefined, reviewRoute: reviewRoute || undefined }),
  });

  return (
    <div className="p-6">
      <h1 className="mb-6 text-xl font-bold text-[var(--color-text)]">Classification</h1>
      <div className="mb-4 flex gap-2">
        <input
          placeholder="Filter by label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2 font-mono text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-faint)]"
        />
        <input
          placeholder="Filter by review route"
          value={reviewRoute}
          onChange={(e) => setReviewRoute(e.target.value)}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2 font-mono text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-faint)]"
        />
      </div>
      <DataTable
        columns={COLUMNS}
        rows={data?.items ?? []}
        rowKey={(row) => row.jobId}
        onRowClick={(row) => navigate(`/documents/${row.jobId}`)}
      />
    </div>
  );
}
```

- [ ] **Step 5: Manual visual check**

Hand to the user: navigate to `/classification` in the running dev app and confirm the table now
uses tinted badges, mono confidence/date columns, and the warm-surface input styling.

- [ ] **Step 6: Run typecheck, lint, and tests**

Hand to the user: `npx tsc -b && npm run lint && npm run test`.
Expected: all clean — `DataTable`/`StatusBadge` have no dedicated tests to break, and no other
test asserts their old class strings.

- [ ] **Step 7: Commit**

```bash
git add src/classiflow/frontend/src/components/DataTable.tsx src/classiflow/frontend/src/components/StatusBadge.tsx src/classiflow/frontend/src/pages/ClassificationPage.tsx
git commit -m "style: restyle Classification table and badges with Archive tokens"
```

---

### Task 7: Document Detail page — structured tabs + Audit-tab timeline reuse

**Files:**
- Modify: `src/classiflow/frontend/src/pages/DocumentDetailPage.tsx`

**Interfaces:**
- Consumes: `fetchJobDetail`, `documentFileUrl`, `JobDetailResponse` from `../api/documents`
  (unchanged), `PdfViewer` from `../components/PdfViewer` (unchanged — not touched by this plan
  per spec Decision 5), `ReclassifyPanel` from `../components/ReclassifyPanel` (unchanged props),
  `StepTimeline` from `../components/StepTimeline` (Task 4 — called with `mode="expanded"` for the
  Audit tab).
- Produces: no new exports. `JobDetailResponse.audit` (an array of `{ jobId, node, event,
  timestamp, durationMs, detail }`) is mapped into `TimelineEntry[]` at the call site (adding a
  `passed: null` field `StepTimeline` doesn't actually read for rendering status, since status
  comes from `entry.status`/`STATUS_DOT` — `audit[].event` values are `"started"|"passed"|
  "failed"`, the same vocabulary `TimelineEntry.status` already uses per `TestLlmJudgeRun`-style
  backend tests) — no change to `StepTimeline`'s prop contract needed.

- [ ] **Step 1: Confirm no test targets this page**

No `DocumentDetailPage.test.tsx` exists (confirmed by inspection). Proceed directly to the
restyle.

- [ ] **Step 2: Restyle the page and replace raw-JSON tabs with structured layouts**

Replace the full contents of `src/classiflow/frontend/src/pages/DocumentDetailPage.tsx`:

```tsx
import { Fragment, useState } from "react";
import { useParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchJobDetail, documentFileUrl } from "../api/documents";
import type { TimelineEntry } from "../api/jobs";
import PdfViewer from "../components/PdfViewer";
import ReclassifyPanel from "../components/ReclassifyPanel";
import StepTimeline from "../components/StepTimeline";

type Tab = "extraction" | "enrichment" | "classification" | "audit";

const TABS: Tab[] = ["extraction", "enrichment", "classification", "audit"];

function ConfidenceBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-[5px] w-24 overflow-hidden rounded-full bg-[var(--color-border-subtle)]">
        <div
          className="h-full bg-[var(--color-success)]"
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </div>
      <span className="font-mono text-sm text-[var(--color-text-muted)]">{value.toFixed(2)}</span>
    </div>
  );
}

function KeyValueGrid({ pairs }: { pairs: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-3 text-sm">
      {pairs.map(([label, value]) => (
        <Fragment key={label}>
          <dt className="pt-0.5 font-mono text-[11px] uppercase tracking-wide text-[var(--color-text-faint)]">
            {label}
          </dt>
          <dd className="m-0 text-[var(--color-text)]">{value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

export default function DocumentDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [tab, setTab] = useState<Tab>("classification");
  const queryClient = useQueryClient();

  const { data } = useQuery({
    queryKey: ["job-detail", jobId],
    queryFn: () => fetchJobDetail(jobId!),
    enabled: !!jobId,
  });

  if (!data) {
    return <p className="p-6 text-[var(--color-text-muted)]">Loading...</p>;
  }

  const auditEntries: TimelineEntry[] = data.audit.map((a) => ({
    node: a.node,
    status: a.event,
    passed: null,
    detail: a.detail,
    timestamp: a.timestamp,
    durationMs: a.durationMs,
  }));

  return (
    <div className="flex h-screen">
      <div className="w-1/2 border-r border-[var(--color-border)]">
        <PdfViewer fileUrl={documentFileUrl(jobId!)} />
      </div>
      <div className="w-1/2 overflow-y-auto p-6">
        <div className="mb-6 flex gap-1 border-b border-[var(--color-border-subtle)]">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-2 text-sm capitalize transition-colors duration-150 ${
                tab === t
                  ? "border-b-2 border-[var(--color-accent)] font-semibold text-[var(--color-text)]"
                  : "text-[var(--color-text-faint)] hover:text-[var(--color-text-muted)]"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {tab === "extraction" && (
          <pre className="whitespace-pre-wrap font-serif text-sm text-[var(--color-text)]">
            {data.enriched?.rawText ?? "No extraction data"}
          </pre>
        )}

        {tab === "enrichment" && data.enriched && (
          <KeyValueGrid
            pairs={Object.entries(data.enriched.entities).map(([key, value]) => [
              key,
              String(value),
            ])}
          />
        )}
        {tab === "enrichment" && !data.enriched && (
          <p className="text-sm text-[var(--color-text-muted)]">No enrichment data</p>
        )}

        {tab === "classification" && data.classification && (
          <div>
            <KeyValueGrid
              pairs={[
                ["Label", data.classification.label ?? "—"],
                ["Confidence", <ConfidenceBar key="conf" value={data.classification.confidence} />],
                [
                  "Review route",
                  <span
                    key="route"
                    className="font-mono text-xs uppercase text-[var(--color-warning)]"
                  >
                    {data.classification.reviewRoute}
                  </span>,
                ],
                [
                  "Second opinion",
                  data.classification.secondOpinionLabel
                    ? `${data.classification.secondOpinionLabel} · ${data.classification.classifierDisagreement ? "disagrees" : "agrees"}`
                    : "—",
                ],
                [
                  "Smells",
                  data.classification.smells.length > 0 ? (
                    <span key="smells" className="flex flex-wrap gap-1.5">
                      {data.classification.smells.map((s) => (
                        <span
                          key={s}
                          className="rounded bg-[var(--color-border-subtle)] px-2 py-0.5 font-mono text-[10.5px] text-[var(--color-warning)]"
                        >
                          {s}
                        </span>
                      ))}
                    </span>
                  ) : (
                    "none"
                  ),
                ],
              ]}
            />
            {data.classification.judgeReasoning && (
              <>
                <p className="mb-2 mt-6 font-mono text-[11px] uppercase tracking-wide text-[var(--color-text-faint)]">
                  Judge reasoning
                </p>
                <p className="text-sm leading-relaxed text-[var(--color-text-muted)]">
                  {data.classification.judgeReasoning}
                </p>
              </>
            )}
            {data.classification.reviewRoute === "human_review" && (
              <div className="mt-6">
                <ReclassifyPanel
                  jobId={jobId!}
                  onSubmitted={() =>
                    queryClient.invalidateQueries({ queryKey: ["job-detail", jobId] })
                  }
                />
              </div>
            )}
          </div>
        )}
        {tab === "classification" && !data.classification && (
          <p className="text-sm text-[var(--color-text-muted)]">No classification data</p>
        )}

        {tab === "audit" && <StepTimeline entries={auditEntries} mode="expanded" />}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Manual visual check**

Hand to the user: open a completed document's detail page and confirm: (a) Enrichment/
Classification tabs show structured key/value rows instead of raw JSON, (b) the confidence bar
renders, (c) smell tags render as pills, (d) the Audit tab shows the full expanded phase timeline
(every phase's steps visible, not collapsed), (e) tabs use the bottom-border-active style.

- [ ] **Step 4: Run typecheck, lint, and tests**

Hand to the user: `npx tsc -b && npm run lint && npm run test`.
Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add src/classiflow/frontend/src/pages/DocumentDetailPage.tsx
git commit -m "style: replace raw JSON dumps with structured layouts, reuse expanded timeline in Audit tab"
```

---

### Task 8: Users & Audit Log pages, `ReclassifyPanel` — final token pass

**Files:**
- Modify: `src/classiflow/frontend/src/pages/UsersPage.tsx`
- Modify: `src/classiflow/frontend/src/pages/AuditLogPage.tsx`
- Modify: `src/classiflow/frontend/src/components/ReclassifyPanel.tsx`

**Interfaces:**
- Consumes: no interface changes anywhere in this task — `fetchUsers`/`createUser`/`updateUser`/
  `deleteUser` from `../api/users`, `fetchAuditPage`/`AuditRecordItem` from `../api/audit`,
  `submitReclassification`/`DOCUMENT_CATEGORIES` from `../api/classification` all unchanged.
- Produces: no new exports. Purely a class-string pass — these three files already use
  `var(--color-*)` Tailwind classes exclusively (no hardcoded colors), so Task 1's token swap
  already re-colors them correctly. This task only needs typographic/spacing polish to match the
  rest of the app (mono for IDs/timestamps, serif headings, consistent input styling) — not a
  full rewrite.

- [ ] **Step 1: Confirm no test targets these files' styling**

No `UsersPage.test.tsx` or `AuditLogPage.test.tsx` exists; `ReclassifyPanel.test.tsx` exists and
asserts behavior (form submission, `aria-label` lookups), not class strings — confirmed safe to
restyle without touching that test file.

- [ ] **Step 2: Restyle `UsersPage`**

In `src/classiflow/frontend/src/pages/UsersPage.tsx`, update the `return` block's className
strings (structure and logic unchanged):

```tsx
  return (
    <div className="p-6">
      <h1 className="mb-6 text-xl font-bold text-[var(--color-text)]">Users</h1>
      <div className="mb-4 flex gap-2">
        <input
          placeholder="new.user@example.com"
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2 font-mono text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-faint)]"
        />
        <button
          onClick={handleAdd}
          className="rounded-md bg-[var(--color-accent)] px-3 py-2 text-sm font-semibold text-[var(--color-bg)]"
        >
          Add
        </button>
      </div>
      <DataTable columns={columns} rows={users} rowKey={(u) => u.email} />
    </div>
  );
```

Also update the action-button classNames inside `columns` (`Actions` column) — replace
`text-sm text-[var(--color-accent)]` with `text-sm font-medium text-[var(--color-accent)]
hover:underline`, and `text-sm text-[var(--color-danger)]` with `text-sm font-medium
text-[var(--color-danger)] hover:underline`, so the action links read distinctly as links rather
than plain text.

- [ ] **Step 3: Restyle `AuditLogPage`**

In `src/classiflow/frontend/src/pages/AuditLogPage.tsx`, update the `COLUMNS` array and `return`
block:

```tsx
const COLUMNS: Column<AuditRecordItem>[] = [
  { header: "Job", render: (r) => <span className="font-mono text-xs">{r.jobId}</span> },
  { header: "Node", render: (r) => r.node },
  { header: "Event", render: (r) => r.event },
  {
    header: "Timestamp",
    render: (r) => (
      <span className="font-mono text-xs text-[var(--color-text-faint)]">
        {new Date(r.timestamp).toLocaleString()}
      </span>
    ),
  },
  { header: "Duration (ms)", render: (r) => <span className="font-mono">{r.durationMs ?? "—"}</span> },
];

export default function AuditLogPage() {
  const [jobId, setJobId] = useState("");
  const navigate = useNavigate();

  const { data } = useQuery({
    queryKey: ["audit", jobId],
    queryFn: () => fetchAuditPage({ jobId: jobId || undefined }),
  });

  return (
    <div className="p-6">
      <h1 className="mb-6 text-xl font-bold text-[var(--color-text)]">Audit Log</h1>
      <input
        placeholder="Filter by job ID"
        value={jobId}
        onChange={(e) => setJobId(e.target.value)}
        className="mb-4 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2 font-mono text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-faint)]"
      />
      <DataTable
        columns={COLUMNS}
        rows={data?.items ?? []}
        rowKey={(r) => `${r.jobId}-${r.node}-${r.timestamp}`}
        onRowClick={(r) => navigate(`/documents/${r.jobId}`)}
      />
    </div>
  );
}
```

- [ ] **Step 4: Restyle `ReclassifyPanel`**

In `src/classiflow/frontend/src/components/ReclassifyPanel.tsx`, update classNames only (JSX
structure, ids, and `aria-label`s unchanged so the existing `ReclassifyPanel.test.tsx` keeps
passing):

```tsx
  return (
    <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <label className="mb-1 block font-mono text-[11px] uppercase tracking-wide text-[var(--color-text-faint)]" htmlFor="reclassify-label">
        Label
      </label>
      <select
        id="reclassify-label"
        aria-label="Label"
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        className="mb-3 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2 text-[var(--color-text)]"
      >
        {DOCUMENT_CATEGORIES.map((category) => (
          <option key={category} value={category}>
            {category}
          </option>
        ))}
      </select>

      <label className="mb-1 block font-mono text-[11px] uppercase tracking-wide text-[var(--color-text-faint)]" htmlFor="reclassify-notes">
        Notes
      </label>
      <textarea
        id="reclassify-notes"
        aria-label="Notes"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        className="mb-3 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2 text-[var(--color-text)]"
      />

      <button
        onClick={handleSubmit}
        disabled={submitting}
        className="rounded-md bg-[var(--color-accent)] px-4 py-2 font-semibold text-[var(--color-bg)] disabled:opacity-50"
      >
        Submit
      </button>
    </div>
  );
```

- [ ] **Step 5: Manual visual check**

Hand to the user: as an admin user, check `/users` and `/audit` render with mono IDs/timestamps
and consistent input/button styling matching the rest of the app; open a human-review document's
detail page and confirm the `ReclassifyPanel` form still works and matches the new palette.

- [ ] **Step 6: Run typecheck, lint, and tests**

Hand to the user: `npx tsc -b && npm run lint && npm run test` (from `src/classiflow/frontend/`).
Expected: all clean, including `ReclassifyPanel.test.tsx` (structure/`aria-label`s untouched).

- [ ] **Step 7: Commit**

```bash
git add src/classiflow/frontend/src/pages/UsersPage.tsx src/classiflow/frontend/src/pages/AuditLogPage.tsx src/classiflow/frontend/src/components/ReclassifyPanel.tsx
git commit -m "style: apply final Archive token pass to Users, Audit Log, and ReclassifyPanel"
```

---

### Task 9: Whole-app verification pass

**Files:** none (verification only — no code changes expected).

**Interfaces:** N/A.

- [ ] **Step 1: Full frontend check**

Hand to the user: from `src/classiflow/frontend/`, run `npx tsc -b && npm run lint && npm run test`.
Expected: all clean — this re-runs everything from Tasks 1-8 together to catch any cross-task
regression (e.g. a shared component restyled in one task breaking an assumption made in another).

- [ ] **Step 2: Full backend check (confirms no accidental backend edits)**

Hand to the user: `uv run poe check` from the repo root.
Expected: passes — this plan makes no backend changes (Global Constraints), so this is a
regression guard, not new work.

- [ ] **Step 3: End-to-end manual walkthrough**

Hand to the user: with both servers running, walk through: log in → upload a document → watch it
on the Processing page through to completion → find it on the Classification page → open its
Document Detail page and check all four tabs → (if admin) check Users and Audit Log pages. Confirm
the whole app now reads as one consistent visual system rather than one polished component in an
otherwise plain shell.

- [ ] **Step 4: Commit (only if Step 1-3 surfaced fixes)**

If any cross-task issue was found and fixed in this task, commit it:

```bash
git add -A
git commit -m "fix: address cross-task regressions found in whole-app verification"
```

If nothing needed fixing, skip this step — there's nothing to commit.

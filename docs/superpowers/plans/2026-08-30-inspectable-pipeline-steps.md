# Inspectable Pipeline Steps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each pipeline step's already-fetched `detail` payload inspectable via click-to-expand,
in both the Processing page's live view and the Document Detail page's Audit tab — both already
share the `StepTimeline` component, so one implementation covers both. Also let a completed phase
expand on click during a live (condensed-mode) job, not just the currently-running one.

**Architecture:** Extract the existing private `KeyValueGrid` helper (currently trapped inside
`DocumentDetailPage.tsx`) into its own shared component, then add local expand/collapse state to
`StepRow` (per-step) and `PhaseGroup` (per-phase) inside `StepTimeline.tsx`, reusing the exact
chevron-toggle visual pattern this codebase already has in `DocumentDetailPage.tsx`'s
`MoreDetails` component. No backend changes — `TimelineEntry.detail` already flows end to end.

**Tech Stack:** React 19, TypeScript, Tailwind v4, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-08-30-inspectable-pipeline-steps-design.md`

## Global Constraints

- Inline expand only — no modal, no side panel (spec Decision 1).
- No expand affordance renders when a step's `detail` is `null` or an empty object (spec Decision 3).
- Expanding one step or phase must never collapse another — independent state per row (spec
  Decisions 3-4).
- A phase's manual expand toggle is a no-op when `expanded` (Audit tab) or `live` is already true —
  both already show steps unconditionally (spec Decision 4).
- No visual redesign beyond what's specified here — the theme/token work is a separate, already
  in-progress effort.

---

### Task 1: Extract `KeyValueGrid` into its own shared component

**Files:**
- Create: `src/classiflow/frontend/src/components/KeyValueGrid.tsx`
- Modify: `src/classiflow/frontend/src/pages/DocumentDetailPage.tsx`

**Interfaces:**
- Produces: `KeyValueGrid({ pairs: [string, React.ReactNode][] })` as a default export, consumed
  by Task 2's `StepRow`.

- [ ] **Step 1: Create the new component file**

```tsx
import { Fragment } from "react";

export default function KeyValueGrid({ pairs }: { pairs: [string, React.ReactNode][] }) {
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
```

This is a verbatim copy of the function currently defined at
`src/classiflow/frontend/src/pages/DocumentDetailPage.tsx:29-42` (down to the class names) — no
behavior change, just a new home.

- [ ] **Step 2: Update `DocumentDetailPage.tsx` to import it instead of defining it locally**

Delete the local `function KeyValueGrid(...) { ... }` definition (lines 29-42 in the current
file — re-read the file first, since earlier tasks in this session may have shifted line numbers)
and add the import alongside the file's other local imports:

```tsx
import KeyValueGrid from "../components/KeyValueGrid";
```

Every existing call site in this file (`<KeyValueGrid pairs={...} />` inside the classification,
knowledge tabs, and inside `MoreDetails`) needs no change — same component name, same prop shape.

- [ ] **Step 3: Verify nothing broke**

```
uv run poe lint
```

No behavior changed, so no test assertions should need updating. If this project has an existing
Vitest suite covering `DocumentDetailPage.tsx`, run it too; otherwise this step's lint pass is
sufficient (this page has no dedicated `.test.tsx` today, per the codebase's own convention of
only testing components with real branching logic — `KeyValueGrid` itself has none).

- [ ] **Step 4: Commit**

```bash
git add src/classiflow/frontend/src/components/KeyValueGrid.tsx src/classiflow/frontend/src/pages/DocumentDetailPage.tsx
git commit -m "refactor: extract KeyValueGrid into its own shared component"
```

---

### Task 2: Inspectable step detail (`StepRow`)

**Files:**
- Modify: `src/classiflow/frontend/src/components/StepTimeline.tsx`
- Modify: `src/classiflow/frontend/src/components/StepTimeline.test.tsx`

**Interfaces:**
- Consumes: `KeyValueGrid` (Task 1, `../components/KeyValueGrid`).
- Produces: no new exports — `StepRow` remains a private function inside `StepTimeline.tsx`.

- [ ] **Step 1: Write the failing tests**

Add to `src/classiflow/frontend/src/components/StepTimeline.test.tsx` (the file already imports
`render`/`screen` from Testing Library and defines the `entry()` helper — extend both):

```tsx
import { fireEvent } from "@testing-library/react";

function entryWithDetail(
  node: string,
  status: string,
  timestamp: string,
  detail: Record<string, unknown> | null,
): TimelineEntry {
  return { ...entry(node, status, timestamp), detail };
}
```

```tsx
  it("a step with detail shows an expand toggle; clicking it reveals the detail fields", () => {
    const entries: TimelineEntry[] = [
      entryWithDetail("node2_format_validation", "passed", "2026-08-24T10:00:00Z", {
        detectedFormat: "pdf",
        confidence: 0.98,
      }),
    ];
    render(<StepTimeline entries={entries} mode="expanded" />);

    expect(screen.queryByText("detectedFormat")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("format validation"));

    expect(screen.getByText("detectedFormat")).toBeInTheDocument();
    expect(screen.getByText("pdf")).toBeInTheDocument();
  });

  it("a step with no detail shows no expand toggle and cannot be clicked open", () => {
    const entries: TimelineEntry[] = [
      entryWithDetail("node1_file_reception", "passed", "2026-08-24T10:00:00Z", null),
    ];
    render(<StepTimeline entries={entries} mode="expanded" />);

    const row = screen.getByText("file reception").closest("button");
    expect(row).toBeDisabled();
  });

  it("expanding one step does not collapse another", () => {
    const entries: TimelineEntry[] = [
      entryWithDetail("node2_format_validation", "passed", "2026-08-24T10:00:00Z", { a: "1" }),
      entryWithDetail("node3_content_validation", "passed", "2026-08-24T10:00:01Z", { b: "2" }),
    ];
    render(<StepTimeline entries={entries} mode="expanded" />);

    fireEvent.click(screen.getByText("format validation"));
    fireEvent.click(screen.getByText("content validation"));

    expect(screen.getByText("a")).toBeInTheDocument();
    expect(screen.getByText("b")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the tests, confirm they fail**

```
npm --prefix src/classiflow/frontend run test -- StepTimeline
```

Expected: FAIL — clicking a step name does nothing yet, and `detectedFormat`/`pdf` are never
rendered because `StepRow` doesn't consume `entry.detail` at all today.

- [ ] **Step 3: Implement**

In `src/classiflow/frontend/src/components/StepTimeline.tsx`, add the import and helper near the
top:

```tsx
import { useState } from "react";
import KeyValueGrid from "./KeyValueGrid";
```

```tsx
function detailPairs(detail: Record<string, unknown>): [string, React.ReactNode][] {
  return Object.entries(detail).map(([key, value]) => [
    key,
    typeof value === "object" && value !== null ? JSON.stringify(value, null, 2) : String(value),
  ]);
}
```

Replace `StepRow` with:

```tsx
function StepRow({ entry, live }: { entry: TimelineEntry; live: boolean }) {
  const [open, setOpen] = useState(false);
  const hasDetail = entry.detail != null && Object.keys(entry.detail).length > 0;

  return (
    <div className="relative flex flex-col gap-1 py-0.5 transition-all duration-150">
      <button
        type="button"
        onClick={() => hasDetail && setOpen((o) => !o)}
        disabled={!hasDetail}
        className="relative flex items-center gap-2.5 text-left disabled:cursor-default"
      >
        <span
          className={`absolute -left-[21px] h-1.5 w-1.5 rounded-full ${live ? "animate-pulse " : ""}${STATUS_DOT[entry.status] ?? "bg-[var(--color-text-muted)]"}`}
        />
        <span
          className={`text-sm ${live ? "font-semibold text-[var(--color-text)]" : "text-[var(--color-text-muted)]"}`}
        >
          {formatNodeName(entry.node)}
        </span>
        <span className="font-mono text-[11px] text-[var(--color-text-faint)]">{entry.node}</span>
        {entry.durationMs != null && (
          <span className="ml-auto font-mono text-[11px] text-[var(--color-text-muted)]">
            {formatDuration(entry.durationMs)}
          </span>
        )}
        {hasDetail && (
          <span
            className={`font-mono text-[11px] text-[var(--color-text-faint)] transition-transform duration-150 ${open ? "rotate-90" : ""}`}
          >
            ▸
          </span>
        )}
      </button>
      {open && hasDetail && (
        <div className="mt-1">
          <KeyValueGrid pairs={detailPairs(entry.detail as Record<string, unknown>)} />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests, confirm they pass**

```
npm --prefix src/classiflow/frontend run test -- StepTimeline
```

- [ ] **Step 5: Run the full frontend suite to confirm no regression**

```
npm --prefix src/classiflow/frontend run test
```

- [ ] **Step 6: Commit**

```bash
git add src/classiflow/frontend/src/components/StepTimeline.tsx src/classiflow/frontend/src/components/StepTimeline.test.tsx
git commit -m "feat: make each pipeline step's detail inspectable"
```

---

### Task 3: Expandable completed phases (`PhaseGroup`)

**Files:**
- Modify: `src/classiflow/frontend/src/components/StepTimeline.tsx`
- Modify: `src/classiflow/frontend/src/components/StepTimeline.test.tsx`

**Interfaces:**
- Consumes: `useState` (already imported by Task 2).
- Produces: no new exports.

- [ ] **Step 1: Write the failing test**

Add to `StepTimeline.test.tsx`:

```tsx
  it("condensed mode: clicking a completed phase's header expands its steps", () => {
    render(<StepTimeline entries={INGESTA_DONE} mode="condensed" />);

    expect(screen.queryByText("node1_file_reception")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Ingesta"));

    expect(screen.getByText("node1_file_reception")).toBeInTheDocument();
    expect(screen.getByText("node2_format_validation")).toBeInTheDocument();
  });

  it("expanded mode: clicking a phase header is a no-op (already showing everything)", () => {
    render(<StepTimeline entries={INGESTA_DONE} mode="expanded" />);

    fireEvent.click(screen.getByText("Ingesta"));

    // Still visible -- nothing broke by the click being a no-op here.
    expect(screen.getByText("node1_file_reception")).toBeInTheDocument();
  });

  it("condensed mode: expanding one completed phase does not collapse a sibling live phase", () => {
    const entries: TimelineEntry[] = [
      ...INGESTA_DONE,
      entry("classification_primary_classifier", "passed", "2026-08-24T10:00:02Z"),
      entry("classification_second_opinion", "started", "2026-08-24T10:00:03Z"),
    ];
    render(<StepTimeline entries={entries} mode="condensed" />);

    fireEvent.click(screen.getByText("Ingesta"));

    expect(screen.getByText("node1_file_reception")).toBeInTheDocument();
    expect(screen.getByText("classification_second_opinion")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the tests, confirm they fail**

```
npm --prefix src/classiflow/frontend run test -- StepTimeline
```

Expected: FAIL — clicking "Ingesta" does nothing today; the phase header isn't a button yet.

- [ ] **Step 3: Implement**

Replace `PhaseGroup`'s header markup with a clickable button, adding local state:

```tsx
function PhaseGroup({ phase, expanded }: { phase: Phase; expanded: boolean }) {
  const [manuallyExpanded, setManuallyExpanded] = useState(false);
  const live = isPhaseLive(phase);
  const dotClass = live
    ? "animate-pulse bg-[var(--color-accent)]"
    : phase.entries.every((e) => e.status === "passed")
      ? "bg-[var(--color-success)]"
      : "bg-[var(--color-danger)]";

  // Condensed mode only auto-expands the phase currently in progress; a phase that's
  // already terminal collapses to its summary line unless the user clicks it open, so a
  // multi-minute job doesn't turn into a wall of already-known-good steps by default.
  const showSteps = expanded || live || manuallyExpanded;

  return (
    <div className="transition-all duration-150">
      <button
        type="button"
        onClick={() => !expanded && !live && setManuallyExpanded((o) => !o)}
        disabled={expanded || live}
        className="relative flex items-center gap-2.5 text-left disabled:cursor-default"
      >
        <span className={`absolute -left-[21px] h-1.5 w-1.5 rounded-full ${dotClass}`} />
        <span className="text-sm font-semibold text-[var(--color-text)]">{phase.name}</span>
        {!showSteps && (
          <span className="font-mono text-[11px] text-[var(--color-text-faint)]">
            {phase.entries.length} step{phase.entries.length === 1 ? "" : "s"}
          </span>
        )}
        {live && <span className="text-sm text-[var(--color-text-muted)]">running…</span>}
      </button>
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
```

- [ ] **Step 4: Run the tests, confirm they pass**

```
npm --prefix src/classiflow/frontend run test -- StepTimeline
```

- [ ] **Step 5: Run the full frontend suite to confirm no regression**

```
npm --prefix src/classiflow/frontend run test
```

- [ ] **Step 6: Commit**

```bash
git add src/classiflow/frontend/src/components/StepTimeline.tsx src/classiflow/frontend/src/components/StepTimeline.test.tsx
git commit -m "feat: let a completed phase expand on click during a live job"
```

---

### Task 4: Whole-app verification

- [ ] Run `uv run poe check` (lint + typecheck + full backend test suite + pre-commit, including
  frontend eslint/prettier and the Vitest suite) — hand to the user per this repo's
  execution-workflow rule.
- [ ] Manual walkthrough (hand to the user, `uv run poe serve` running):
  1. Start processing a document; while a phase is running, confirm its live steps show expand
     toggles for any step that has detail, and that clicking one reveals the `KeyValueGrid`.
  2. While that job is still running, click a completed phase's header (e.g. "Ingesta" once it's
     done) and confirm its steps appear, without affecting the still-live phase's own display.
  3. Once the job finishes, open its Document Detail page's Audit tab and confirm every phase's
     steps are visible (unchanged `expanded` behavior) and each step's detail is still
     inspectable the same way.

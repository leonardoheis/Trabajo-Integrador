# Inspectable Pipeline Steps — Design Spec

## Status

Draft — pending user review.

## Context

`StepTimeline.tsx` already renders one row per pipeline step (`StepRow`) grouped into phases
(`PhaseGroup`) — used in two places: the Processing page's live view (`mode="condensed"`,
default) and the Document Detail page's Audit tab (`mode="expanded"`). Both already consume the
same `TimelineEntry` shape, which carries a `detail: Record<string, unknown> | null` field per
step — populated end to end from the backend (`DocumentStepSchema`/`AuditRecordSchema`) — but
`StepRow` never renders it. Every step's structured detail (validation results, extraction
metadata, classification scores, whatever that node recorded) is fetched and silently discarded.

Separately, `PhaseGroup`'s condensed mode only renders individual `StepRow`s for the phase
currently in progress (`showSteps = expanded || live`); a completed phase collapses to a
`"4 steps"` summary with no way to see its rows at all during a live job — only after the job
finishes and the user navigates to the Audit tab (which passes `mode="expanded"`, showing every
phase's steps unconditionally).

This spec closes both gaps: reference screenshot shown during design was a LangGraph demo console
("Research Agent Console") with a live step list showing per-step status and sub-detail lines —
the useful idea taken from it is "each step in the pipeline is inspectable," not its specific
visual style (light dev-console aesthetic is out of scope here; see Non-Goals).

Because Processing and the Audit tab already share `StepTimeline`, everything decided here
applies to both automatically — no separate implementation for each page.

## Decisions

### 1. Inline expand, not a modal or side panel

Clicking a step row expands it in place, in the space already reserved by the timeline's rail
layout. No new overlay/modal component is introduced — this app has no existing modal pattern,
and inline expand keeps the interaction consistent with the rail-based layout already in place.

### 2. Detail renders via `KeyValueGrid`, extracted to a shared component

`KeyValueGrid` (one row per field: mono uppercase label, value) already exists — but it's
currently a private, unexported function inside `DocumentDetailPage.tsx`
(`src/classiflow/frontend/src/pages/DocumentDetailPage.tsx:29-42`). `StepTimeline.tsx` needs it
too, so it moves to its own file:

**New file:** `src/classiflow/frontend/src/components/KeyValueGrid.tsx`

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

(Verbatim move — no behavior change.) `DocumentDetailPage.tsx` drops its local definition and
imports it instead; every existing call site there (`ConfidenceBar`/label rows, `MoreDetails`'s
`pairs`) keeps working unchanged since the prop shape is identical.

A `detail: Record<string, unknown>` needs converting to `[string, ReactNode][]` pairs. New
helper in `StepTimeline.tsx`, matching the existing stringify-nested-values convention already
used for `MoreDetails`'s "SVM scores"/"OOD metrics" cells in `DocumentDetailPage.tsx`:

```tsx
function detailPairs(detail: Record<string, unknown>): [string, React.ReactNode][] {
  return Object.entries(detail).map(([key, value]) => [
    key,
    typeof value === "object" && value !== null
      ? JSON.stringify(value, null, 2)
      : String(value),
  ]);
}
```

### 3. `StepRow` gains a click-to-expand toggle, matching `MoreDetails`'s existing pattern

`MoreDetails` (`DocumentDetailPage.tsx:44-60`) already has the exact interaction this spec wants:
local `useState<boolean>`, a `▸` chevron that rotates 90° when open, content revealed below on
expand. `StepRow` adopts the same visual language:

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
        <div className="ml-0 mt-1 pl-0">
          <KeyValueGrid pairs={detailPairs(entry.detail as Record<string, unknown>)} />
        </div>
      )}
    </div>
  );
}
```

No expand affordance renders at all when `entry.detail` is `null` or an empty object — nothing
to inspect, no dead-end click.

### 4. `PhaseGroup` gains a click-to-expand toggle for completed phases

Today `showSteps = expanded || live` — a completed phase in condensed mode never shows its rows.
Add local state so a user can manually expand a completed phase during a live job (or in condensed
mode generally), independent of the `expanded` prop (which stays as the Audit tab's always-on
override) and independent of `live` (which still auto-shows the in-progress phase without a
click):

```tsx
function PhaseGroup({ phase, expanded }: { phase: Phase; expanded: boolean }) {
  const [manuallyExpanded, setManuallyExpanded] = useState(false);
  const live = isPhaseLive(phase);
  const dotClass = /* unchanged */;
  const showSteps = expanded || live || manuallyExpanded;

  return (
    <div className="transition-all duration-150">
      <button
        type="button"
        onClick={() => !expanded && !live && setManuallyExpanded((o) => !o)}
        disabled={expanded || live}
        className="relative flex items-center gap-2.5 text-left disabled:cursor-default"
      >
        {/* unchanged dot + phase name */}
        {!showSteps && (
          <span className="font-mono text-[11px] text-[var(--color-text-faint)]">
            {phase.entries.length} step{phase.entries.length === 1 ? "" : "s"}
          </span>
        )}
        {live && <span className="text-sm text-[var(--color-text-muted)]">running…</span>}
      </button>
      {/* unchanged: steps rendering when showSteps */}
    </div>
  );
}
```

The click handler is a no-op while `expanded` (Audit tab, already showing everything) or `live`
(already auto-expanded) — it only does anything for a completed phase in condensed mode, which is
exactly the gap being closed. Multiple phases can be expanded independently; expanding one does
not collapse another (same independent-state principle as step rows).

## Non-Goals

- **No visual redesign matching the reference screenshot's specific look** (dev-console
  aesthetic, colored status dots with pill tags, live sub-status lines) — that's the separate
  "Archive, Daylight" theme work already in progress. This spec is purely about making existing
  data inspectable, not restyling the timeline.
- **No changes to what data nodes record in `detail`** — this spec only renders what's already
  captured; it doesn't add new fields to any node's audit/step record.
- **No changes to the Processing page's polling or `TimelineEntry` fetching** — purely a rendering
  change inside `StepTimeline.tsx`.
- **No changes to `DocumentDetailPage.tsx`'s other tabs** (extraction, enrichment, classification,
  knowledge) — only the `KeyValueGrid` extraction (a verbatim move) and the Audit tab's existing
  `StepTimeline` usage (unchanged call site — same props, same behavior, gets the new capability
  for free).

## Testing

`StepTimeline.test.tsx` already exists (per the codebase's own component-test convention for
pieces with real branching logic). Extend it with:
- A step with non-empty `detail` shows an expand affordance; clicking it reveals the `KeyValueGrid`
  content; a step with `null`/empty `detail` shows no affordance at all.
- A completed (non-live) phase in condensed mode shows a `"N steps"` summary and no rows by
  default; clicking the phase header reveals its rows.
- Clicking a phase header has no effect when `expanded` is true or the phase is `live` (both
  already show steps unconditionally).
- Expanding two different steps (or phases) independently — verify both stay expanded
  simultaneously, neither collapses the other.

No backend tests needed — no backend code changes.

Run `uv run poe check` (includes frontend eslint/prettier and the Vitest suite) per the project's
standard gate — hand to the user rather than running directly.

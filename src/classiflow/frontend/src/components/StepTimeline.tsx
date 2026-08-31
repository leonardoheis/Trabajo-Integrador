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

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes} m ${seconds} s`;
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
        className={`text-base ${live ? "font-semibold text-[var(--color-text)]" : "text-[var(--color-text-muted)]"}`}
      >
        {formatNodeName(entry.node)}
      </span>
      <span className="font-mono text-[11px] text-[var(--color-text-faint)]">{entry.node}</span>
      {entry.durationMs != null && (
        <span className="ml-auto font-mono text-[11px] text-[var(--color-text-muted)]">
          {formatDuration(entry.durationMs)}
        </span>
      )}
    </div>
  );
}

function PhaseGroup({ phase, expanded }: { phase: Phase; expanded: boolean }) {
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
        <span className="text-base font-semibold text-[var(--color-text)]">{phase.name}</span>
        {!showSteps && (
          <span className="font-mono text-[11px] text-[var(--color-text-faint)]">
            {phase.entries.length} step{phase.entries.length === 1 ? "" : "s"}
          </span>
        )}
        {live && <span className="text-base text-[var(--color-text-muted)]">running…</span>}
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
            <p className="pl-0 text-base text-[var(--color-text-muted)]">
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
    return <p className="text-base text-[var(--color-text-muted)]">Waiting for the first step…</p>;
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

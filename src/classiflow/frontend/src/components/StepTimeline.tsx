import type { TimelineEntry } from "../api/jobs";

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
    .split("_")
    .join(" ");
}

// Wizard-style stepper connected by a single rail, matching the reference "Agent
// Pipeline" mockup's shape: a steady vertical trace of what's happened, one node
// expanded with its live status where the job actually is right now. There's no
// upfront list of pending steps -- the backend doesn't expose a fixed node sequence
// ahead of time (ingesta/enrichment/classification stages differ per job, and a
// rejected job skips remaining nodes entirely), so only what's actually
// happened/is happening is shown.
export default function StepTimeline({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) {
    return <p className="text-sm text-[var(--color-text-muted)]">Waiting for the first step…</p>;
  }

  const lastIndex = entries.length - 1;
  const last = entries[lastIndex];
  const isLastStepLive = !TERMINAL_STATUSES.has(last.status);
  const completed = entries.slice(0, isLastStepLive ? lastIndex : lastIndex + 1);

  return (
    <div className="relative flex flex-col gap-2.5 border-l border-[var(--color-border)] pl-4">
      {completed.map((entry, i) => (
        <div
          key={`${entry.node}-${entry.timestamp}-${i}`}
          className="relative flex items-center gap-2.5"
        >
          <span
            className={`absolute -left-[21px] h-1.5 w-1.5 rounded-full ${STATUS_DOT[entry.status] ?? "bg-[var(--color-text-muted)]"}`}
          />
          <span className="text-sm text-[var(--color-text-muted)]">
            {formatNodeName(entry.node)}
          </span>
          <span className="font-mono text-[11px] text-[var(--color-text-muted)]">{entry.node}</span>
        </div>
      ))}

      {isLastStepLive && (
        <div className="relative flex flex-col gap-0.5 py-0.5">
          <span
            className={`absolute -left-[21px] top-1.5 h-1.5 w-1.5 animate-pulse rounded-full ${STATUS_DOT[last.status] ?? "bg-[var(--color-accent)]"}`}
          />
          <div className="flex items-center gap-2.5">
            <span className="font-semibold text-[var(--color-text)]">
              {formatNodeName(last.node)}
            </span>
            <span className="font-mono text-[11px] text-[var(--color-text-muted)]">
              {last.node}
            </span>
          </div>
          <p className="text-sm text-[var(--color-text-muted)]">{last.status}…</p>
        </div>
      )}
    </div>
  );
}

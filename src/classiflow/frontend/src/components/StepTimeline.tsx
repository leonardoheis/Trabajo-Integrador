import type { TimelineEntry } from "../api/jobs";

const STATUS_COLOR: Record<string, string> = {
  passed: "bg-[var(--color-success)]",
  failed: "bg-[var(--color-danger)]",
  started: "bg-[var(--color-accent)]",
  processing: "bg-[var(--color-accent)]",
};

export default function StepTimeline({ entries }: { entries: TimelineEntry[] }) {
  return (
    <div className="flex flex-col gap-3">
      {entries.map((entry, i) => (
        <div key={`${entry.node}-${entry.timestamp}-${i}`} className="flex gap-3">
          <div
            className={`mt-1 h-2 w-2 shrink-0 rounded-full ${STATUS_COLOR[entry.status] ?? "bg-[var(--color-text-muted)]"}`}
          />
          <div>
            <p className="font-semibold">{entry.node}</p>
            <p className="text-sm text-[var(--color-text-muted)]">{entry.status}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

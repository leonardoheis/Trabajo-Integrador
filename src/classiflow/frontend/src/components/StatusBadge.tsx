const COLORS: Record<string, { dot: string; label: string; cls: string }> = {
  accept: {
    dot: "var(--color-success)",
    label: "auto-accept",
    cls: "bg-[var(--color-success-bg)] text-[var(--color-success)]",
  },
  human_review: {
    dot: "var(--color-warning)",
    label: "human review",
    cls: "bg-[var(--color-warning-bg)] text-[var(--color-warning)]",
  },
  llm_judge: {
    dot: "var(--color-accent)",
    label: "llm judge",
    cls: "bg-[var(--color-accent-subtle)] text-[var(--color-accent-text)]",
  },
  escalate: {
    dot: "var(--color-danger)",
    label: "escalate",
    cls: "bg-[var(--color-danger-bg)] text-[var(--color-danger)]",
  },
  rejected: {
    dot: "var(--color-danger)",
    label: "rejected",
    cls: "bg-[var(--color-danger-bg)] text-[var(--color-danger)]",
  },
  failed: {
    dot: "var(--color-danger)",
    label: "failed",
    cls: "bg-[var(--color-danger-bg)] text-[var(--color-danger)]",
  },
};

export default function StatusBadge({ status }: { status: string }) {
  const config = COLORS[status];
  if (!config) {
    return (
      <span className="rounded-full bg-[var(--color-bg-inset)] px-2.5 py-0.5 font-mono text-[11px] font-medium text-[var(--color-text-muted)]">
        {status}
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-[11px] font-medium ${config.cls}`}
    >
      <span className="h-1.5 w-1.5 rounded-full flex-shrink-0" style={{ background: config.dot }} />
      {config.label}
    </span>
  );
}

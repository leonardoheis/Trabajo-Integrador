const COLORS: Record<string, string> = {
  accept: "bg-[var(--color-success)]/20 text-[var(--color-success)]",
  human_review: "bg-[var(--color-warning)]/20 text-[var(--color-warning)]",
  llm_judge: "bg-[var(--color-accent)]/20 text-[var(--color-accent)]",
  rejected: "bg-[var(--color-danger)]/20 text-[var(--color-danger)]",
  failed: "bg-[var(--color-danger)]/20 text-[var(--color-danger)]",
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

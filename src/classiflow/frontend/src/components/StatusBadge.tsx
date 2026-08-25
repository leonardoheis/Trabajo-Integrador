const COLORS: Record<string, string> = {
  accept: "bg-[var(--color-success)]",
  human_review: "bg-[var(--color-warning)]",
  llm_judge: "bg-[var(--color-accent)]",
};

export default function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs text-black ${COLORS[status] ?? "bg-[var(--color-text-muted)]"}`}
    >
      {status}
    </span>
  );
}

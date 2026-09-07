import { useState } from "react";
import { reopenClassification } from "../api/classification";

export default function ReopenPanel({
  jobId,
  onReopened,
}: {
  jobId: string;
  onReopened: () => void;
}) {
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleReopen(): Promise<void> {
    setSubmitting(true);
    setError(null);
    try {
      await reopenClassification(jobId, reason);
      setReason("");
      onReopened();
    } catch {
      // Surfaced rather than swallowed: a reopen that silently fails leaves the
      // document filed under the wrong label with no signal to the admin.
      setError("Could not reopen this decision. It may already be under review.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="rounded-md border border-[var(--color-status-review)] bg-[var(--color-surface)] p-4">
      <p className="mb-1 font-mono text-[11px] uppercase tracking-wide text-[var(--color-status-review)]">
        Reopen review
      </p>
      <p className="mb-3 text-sm text-[var(--color-text-muted)]">
        Returns this document to the review queue for a fresh decision. The current label is kept
        until someone re-decides.
      </p>

      <label
        className="mb-1 block font-mono text-[11px] uppercase tracking-wide text-[var(--color-text-faint)]"
        htmlFor="reopen-reason"
      >
        Reason
      </label>
      <textarea
        id="reopen-reason"
        aria-label="Reason"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Why is this decision being reopened?"
        className="mb-3 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2 text-[var(--color-text)] placeholder:text-[var(--color-text-faint)]"
      />

      {error && <p className="mb-3 text-sm text-[var(--color-danger)]">{error}</p>}

      <button
        onClick={handleReopen}
        disabled={submitting || reason.trim() === ""}
        className="rounded-md border border-[var(--color-status-review)] px-4 py-2 font-semibold text-[var(--color-status-review)] disabled:opacity-50"
      >
        {submitting ? "Reopening…" : "Reopen review"}
      </button>
    </div>
  );
}

import { useState } from "react";
import { submitReclassification, DOCUMENT_CATEGORIES } from "../api/classification";

export default function ReclassifyPanel({
  jobId,
  onSubmitted,
}: {
  jobId: string;
  onSubmitted: () => void;
}) {
  const [label, setLabel] = useState<string>(DOCUMENT_CATEGORIES[0]);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(): Promise<void> {
    setSubmitting(true);
    try {
      await submitReclassification(jobId, label, notes);
      onSubmitted();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="rounded-md border border-[var(--color-border)] p-4">
      <label className="mb-1 block text-sm" htmlFor="reclassify-label">
        Label
      </label>
      <select
        id="reclassify-label"
        aria-label="Label"
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        className="mb-3 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2"
      >
        {DOCUMENT_CATEGORIES.map((category) => (
          <option key={category} value={category}>
            {category}
          </option>
        ))}
      </select>

      <label className="mb-1 block text-sm" htmlFor="reclassify-notes">
        Notes
      </label>
      <textarea
        id="reclassify-notes"
        aria-label="Notes"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        className="mb-3 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2"
      />

      <button
        onClick={handleSubmit}
        disabled={submitting}
        className="rounded-md bg-[var(--color-accent)] px-4 py-2 text-white disabled:opacity-50"
      >
        Submit
      </button>
    </div>
  );
}

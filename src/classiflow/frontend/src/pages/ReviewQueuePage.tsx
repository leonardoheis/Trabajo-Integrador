import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchReviewQueue } from "../api/review";
import ReclassifyPanel from "../components/ReclassifyPanel";

export default function ReviewQueuePage() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["review-queue"],
    queryFn: fetchReviewQueue,
  });

  if (isLoading) {
    return (
      <div className="h-full overflow-y-auto p-6 font-mono text-sm text-[var(--color-text-faint)]">
        Loading…
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="h-full overflow-y-auto p-6">
        <h1 className="mb-6 text-2xl font-bold text-[var(--color-text)]">Review Queue</h1>
        <p className="font-mono text-sm text-[var(--color-text-faint)]">
          No documents pending human review.
        </p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <h1 className="mb-1 text-2xl font-bold text-[var(--color-text)]">Review Queue</h1>
      <p className="mb-6 font-mono text-sm text-[var(--color-text-faint)]">
        {data.length} document{data.length === 1 ? "" : "s"} awaiting human classification
      </p>
      <div className="flex flex-col gap-6">
        {data.map((item) => (
          <div
            key={item.jobId}
            className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-5"
          >
            <div className="mb-3 flex flex-wrap items-start gap-x-6 gap-y-1">
              <div>
                <span className="font-mono text-[11px] uppercase tracking-wide text-[var(--color-text-faint)]">
                  Job
                </span>
                <p className="font-mono text-sm text-[var(--color-text)]">{item.jobId}</p>
              </div>
              <div>
                <span className="font-mono text-[11px] uppercase tracking-wide text-[var(--color-text-faint)]">
                  Predicted label
                </span>
                <p className="text-sm text-[var(--color-text)]">{item.label ?? "—"}</p>
              </div>
              <div>
                <span className="font-mono text-[11px] uppercase tracking-wide text-[var(--color-text-faint)]">
                  Confidence
                </span>
                <p className="font-mono text-sm text-[var(--color-text)]">
                  {item.confidence.toFixed(2)}
                </p>
              </div>
              <div>
                <span className="font-mono text-[11px] uppercase tracking-wide text-[var(--color-text-faint)]">
                  Route
                </span>
                <p className="text-sm text-[var(--color-text)]">{item.reviewRoute}</p>
              </div>
              {item.smells.length > 0 && (
                <div>
                  <span className="font-mono text-[11px] uppercase tracking-wide text-[var(--color-text-faint)]">
                    Smells
                  </span>
                  <p className="text-sm text-[var(--color-text-muted)]">{item.smells.join(", ")}</p>
                </div>
              )}
              {item.foreignMunicipality && (
                <div>
                  <span className="font-mono text-[11px] uppercase tracking-wide text-[var(--color-text-faint)]">
                    Foreign municipality
                  </span>
                  <p className="text-sm text-[var(--color-text-muted)]">
                    {item.foreignMunicipality}
                  </p>
                </div>
              )}
            </div>
            <ReclassifyPanel
              jobId={item.jobId}
              onSubmitted={() => {
                void queryClient.invalidateQueries({ queryKey: ["review-queue"] });
                void queryClient.invalidateQueries({ queryKey: ["jobs"] });
              }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

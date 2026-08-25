import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchRunningJobs,
  fetchJobTimeline,
  type JobSummary,
  type TimelineEntry,
} from "../api/jobs";
import StepTimeline from "../components/StepTimeline";

const REFETCH_INTERVAL_MS = 10_000;

function JobCard({ job }: { job: JobSummary }) {
  const [entries, setEntries] = useState<TimelineEntry[]>([]);

  useEffect(() => {
    let cancelled = false;

    fetchJobTimeline(job.jobId)
      .then((backfilled) => {
        if (!cancelled) {
          setEntries(backfilled);
        }
      })
      .catch(() => {});

    const source = new EventSource(`/pipeline/${job.jobId}/events`);
    source.addEventListener("node_update", (event) => {
      const payload = JSON.parse((event as MessageEvent<string>).data) as {
        node: string;
        status: string;
        timestamp: string;
      };
      setEntries((prev) => [
        ...prev,
        {
          node: payload.node,
          status: payload.status,
          passed: null,
          detail: null,
          timestamp: payload.timestamp,
          durationMs: null,
        },
      ]);
    });

    return () => {
      cancelled = true;
      source.close();
    };
  }, [job.jobId]);

  return (
    <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <p className="font-semibold">{job.filename}</p>
      <p className="mb-3 text-xs text-[var(--color-text-muted)]">{job.jobId}</p>
      <StepTimeline entries={entries} />
    </div>
  );
}

export default function ProcessingPage() {
  const { data: jobs = [] } = useQuery({
    queryKey: ["running-jobs"],
    queryFn: fetchRunningJobs,
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const queued = jobs.filter((j) => j.status === "queued");
  const processing = jobs.filter((j) => j.status === "processing");

  return (
    <div className="p-6">
      <h1 className="mb-4 text-xl font-semibold">Processing</h1>

      <h2 className="mb-2 text-sm uppercase text-[var(--color-text-muted)]">Queued</h2>
      <div className="mb-6 flex flex-col gap-2">
        {queued.map((job) => (
          <div
            key={job.jobId}
            className="rounded-md border border-[var(--color-border)] p-2 text-sm"
          >
            {job.filename}
          </div>
        ))}
        {queued.length === 0 && <p className="text-sm text-[var(--color-text-muted)]">None</p>}
      </div>

      <h2 className="mb-2 text-sm uppercase text-[var(--color-text-muted)]">Processing</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {processing.map((job) => (
          <JobCard key={job.jobId} job={job} />
        ))}
      </div>
    </div>
  );
}

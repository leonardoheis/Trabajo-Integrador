import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchRunningJobs,
  fetchJobTimeline,
  uploadDocuments,
  type JobSummary,
  type TimelineEntry,
} from "../api/jobs";
import StepTimeline from "../components/StepTimeline";
import { getToken } from "../auth/tokenStorage";

// ponytail: 2s polling misses very fast jobs less often than the original 10s, but a
// job that completes in under 2s can still slip through entirely -- an SSE-driven
// "job appeared" signal (independent of polling) would close that gap fully if it
// ever matters.
const REFETCH_INTERVAL_MS = 2_000;

function UploadForm() {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<File[]>([]);

  const upload = useMutation({
    mutationFn: uploadDocuments,
    onSuccess: () => {
      setSelected([]);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
      queryClient.invalidateQueries({ queryKey: ["running-jobs"] });
    },
  });

  return (
    <div className="mb-8 flex items-center gap-3 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".pdf,.docx,image/*"
        onChange={(e) => setSelected(Array.from(e.target.files ?? []))}
        className="flex-1 text-sm text-[var(--color-text-muted)] file:mr-3 file:rounded-md file:border-0 file:bg-[var(--color-border-subtle)] file:px-3 file:py-1.5 file:font-mono file:text-xs file:text-[var(--color-text)]"
      />
      <button
        onClick={() => upload.mutate(selected)}
        disabled={selected.length === 0 || upload.isPending}
        className="rounded-md bg-[var(--color-accent)] px-3 py-2 text-sm font-semibold text-[var(--color-bg)] disabled:opacity-50"
      >
        {upload.isPending ? "Uploading…" : `Upload${selected.length > 1 ? ` (${selected.length})` : ""}`}
      </button>
      {upload.isError && (
        <span className="text-sm text-[var(--color-danger)]">Upload failed. Try again.</span>
      )}
    </div>
  );
}

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

    // EventSource can't set an Authorization header (a browser limitation), so the
    // token travels as a query param instead -- see get_current_user_from_query_token
    // in api/dependencies.py for the matching backend side.
    const token = getToken();
    const source = new EventSource(
      `/pipeline/${job.jobId}/events?token=${encodeURIComponent(token ?? "")}`,
    );
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
    <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-4 transition-all duration-150">
      <p className="font-semibold text-[var(--color-text)]">{job.filename}</p>
      <p className="mb-4 font-mono text-xs text-[var(--color-text-faint)]">{job.jobId}</p>
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
      <h1 className="mb-6 text-xl font-bold text-[var(--color-text)]">Processing</h1>

      <UploadForm />

      <p className="mb-2 font-mono text-[11px] uppercase tracking-wider text-[var(--color-text-faint)]">
        Queued — {queued.length}
      </p>
      <div className="mb-8 flex flex-col gap-2">
        {queued.map((job) => (
          <div
            key={job.jobId}
            className="flex items-center justify-between rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
          >
            <span className="text-[var(--color-text)]">{job.filename}</span>
            <span className="text-[var(--color-text-faint)]">waiting for a worker</span>
          </div>
        ))}
        {queued.length === 0 && <p className="text-sm text-[var(--color-text-muted)]">None</p>}
      </div>

      <p className="mb-2 font-mono text-[11px] uppercase tracking-wider text-[var(--color-text-faint)]">
        Processing — {processing.length}
      </p>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {processing.map((job) => (
          <JobCard key={job.jobId} job={job} />
        ))}
      </div>
    </div>
  );
}

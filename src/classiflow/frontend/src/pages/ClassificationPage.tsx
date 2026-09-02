import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { fetchJobsPage, type ClassificationSummary, type SortField } from "../api/documents";
import { pipelineWarmup } from "../api/jobs";
import { synchronizeKb, type SynchronizeKbResult } from "../api/knowledge";
import { fetchReviewQueue } from "../api/review";
import DataTable, { type Column } from "../components/DataTable";
import StatusBadge from "../components/StatusBadge";

function LabelChip({ label }: { label: string | null }) {
  if (!label) return <span className="text-[var(--color-text-faint)]">—</span>;
  return (
    <span className="inline-block rounded bg-[var(--color-accent-subtle)] px-2 py-0.5 font-mono text-xs font-medium capitalize text-[var(--color-accent-text)]">
      {label.replace(/_/g, " ")}
    </span>
  );
}

function ConfidenceCell({ confidence, noData }: { confidence: number; noData: boolean }) {
  if (noData) return <span className="font-mono text-[var(--color-text-faint)]">—</span>;
  const pct = Math.round(confidence * 100);
  const color =
    pct >= 80
      ? "var(--color-status-pass)"
      : pct >= 60
        ? "var(--color-status-review)"
        : "var(--color-status-escalate)";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-14 overflow-hidden rounded-full bg-[var(--color-border)]">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="font-mono text-sm tabular-nums text-[var(--color-text-muted)]">
        {confidence.toFixed(2)}
      </span>
    </div>
  );
}

const COLUMNS: Column<ClassificationSummary>[] = [
  { header: "Filename", sortKey: "filename", render: (row) => row.filename },
  {
    header: "Label",
    sortKey: "label",
    render: (row) => <LabelChip label={row.label} />,
  },
  {
    header: "Review Route",
    // reviewRoute is "n/a" when the job produced no classification record
    // (rejected duplicate, failed pipeline) -- show the job status instead.
    render: (row) => (
      <StatusBadge status={row.reviewRoute === "n/a" ? row.status : row.reviewRoute} />
    ),
  },
  {
    header: "Confidence",
    sortKey: "confidence",
    render: (row) => (
      <ConfidenceCell confidence={row.confidence} noData={row.reviewRoute === "n/a"} />
    ),
  },
  { header: "Judged", render: (row) => (row.judgedByLlm ? "Yes" : "No") },
  { header: "Indexed", sortKey: "indexed", render: (row) => (row.indexed ? "Yes" : "No") },
  {
    header: "Created",
    sortKey: "createdAt",
    render: (row) => (
      <span className="font-mono text-sm text-[var(--color-text-faint)]">
        {new Date(row.createdAt).toLocaleString()}
      </span>
    ),
  },
];

const PAGE_SIZE_OPTIONS = [5, 10, 15, 20, 50, 100] as const;

export default function ClassificationPage() {
  useEffect(() => {
    pipelineWarmup().catch(() => {});
  }, []);

  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZE_OPTIONS[1]);
  const [sortField, setSortField] = useState<SortField | undefined>(undefined);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [syncResult, setSyncResult] = useState<SynchronizeKbResult | null>(null);

  const { data: reviewQueue } = useQuery({
    queryKey: ["review-queue"],
    queryFn: fetchReviewQueue,
  });

  const { data: allJobs } = useQuery({
    queryKey: ["jobs-all-kpi"],
    queryFn: () => fetchJobsPage({ pageSize: 10000 }),
  });

  const kpi = (() => {
    const items = allJobs?.items ?? [];
    const classified = items.filter((r) => r.reviewRoute !== "n/a");
    const autoAccepted = classified.filter((r) => r.reviewRoute === "accept");
    const autoRate = classified.length > 0 ? autoAccepted.length / classified.length : null;
    const avgConf =
      classified.length > 0
        ? classified.reduce((s, r) => s + r.confidence, 0) / classified.length
        : null;
    return { total: items.length, autoRate, avgConf, reviewCount: reviewQueue?.length ?? 0 };
  })();

  const syncMutation = useMutation({
    mutationFn: synchronizeKb,
    onSuccess: (result) => {
      setSyncResult(result);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const { data } = useQuery({
    queryKey: ["jobs", search, page, pageSize, sortField, sortDir],
    queryFn: () =>
      fetchJobsPage({
        search: search || undefined,
        page,
        pageSize,
        sort: sortField,
        sortDir,
      }),
  });

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1;

  function handleSortChange(key: string): void {
    const field = key as SortField;
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("asc");
    }
    setPage(1);
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <h1 className="mb-6 text-2xl font-bold text-[var(--color-text)]">Classification</h1>
      <div className="mb-5 flex gap-4 font-mono text-sm">
        <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-2">
          <span className="text-[var(--color-text-faint)]">Total </span>
          <span className="font-semibold text-[var(--color-text)]">{kpi.total}</span>
        </div>
        <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-2">
          <span className="text-[var(--color-text-faint)]">Auto-accept rate </span>
          <span className="font-semibold text-[var(--color-text)]">
            {kpi.autoRate !== null ? `${(kpi.autoRate * 100).toFixed(1)}%` : "—"}
          </span>
        </div>
        <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-2">
          <span className="text-[var(--color-text-faint)]">Avg confidence </span>
          <span className="font-semibold text-[var(--color-text)]">
            {kpi.avgConf !== null ? kpi.avgConf.toFixed(2) : "—"}
          </span>
        </div>
        <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-2">
          <span className="text-[var(--color-text-faint)]">Pending review </span>
          <span className="font-semibold text-[var(--color-text)]">{kpi.reviewCount}</span>
        </div>
      </div>
      <div className="mb-4 flex items-center">
        <input
          placeholder="Filter by label or filename"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2 font-mono text-base text-[var(--color-text)] placeholder:text-[var(--color-text-faint)]"
        />
        <button
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending}
          className="ml-2 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-base font-semibold text-[var(--color-accent)] disabled:opacity-50"
        >
          {syncMutation.isPending ? "Syncing…" : "Sync Knowledge Base"}
        </button>
        {syncResult && (
          <span className="ml-3 font-mono text-sm text-[var(--color-text-faint)]">
            Indexed {syncResult.indexedJobIds.length}, skipped {syncResult.skippedCount}
          </span>
        )}
      </div>
      <DataTable
        columns={COLUMNS}
        rows={data?.items ?? []}
        rowKey={(row) => row.jobId}
        onRowClick={(row) => navigate(`/documents/${row.jobId}`)}
        sort={sortField ? { key: sortField, dir: sortDir } : undefined}
        onSortChange={handleSortChange}
      />
      <div className="mt-4 flex items-center justify-between font-mono text-sm text-[var(--color-text-faint)]">
        <div className="flex items-center gap-3">
          <span>{data ? `${data.total} document${data.total === 1 ? "" : "s"}` : ""}</span>
          <label className="flex items-center gap-1.5">
            Rows
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-1.5 py-0.5 text-[var(--color-text)]"
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded-md border border-[var(--color-border)] px-2.5 py-1 text-[var(--color-text-muted)] disabled:opacity-40"
          >
            Prev
          </button>
          <span>
            Page {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="rounded-md border border-[var(--color-border)] px-2.5 py-1 text-[var(--color-text-muted)] disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

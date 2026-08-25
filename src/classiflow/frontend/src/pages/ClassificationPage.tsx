import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { fetchJobsPage, type ClassificationSummary } from "../api/documents";
import DataTable, { type Column } from "../components/DataTable";
import StatusBadge from "../components/StatusBadge";

const COLUMNS: Column<ClassificationSummary>[] = [
  { header: "Filename", render: (row) => row.filename },
  { header: "Label", render: (row) => row.label ?? "—" },
  { header: "Review Route", render: (row) => <StatusBadge status={row.reviewRoute} /> },
  {
    header: "Confidence",
    render: (row) => (
      <span className="font-mono text-[var(--color-text-muted)]">
        {row.confidence.toFixed(2)}
      </span>
    ),
  },
  { header: "Judged", render: (row) => (row.judgedByLlm ? "Yes" : "No") },
  {
    header: "Created",
    render: (row) => (
      <span className="font-mono text-xs text-[var(--color-text-faint)]">
        {new Date(row.createdAt).toLocaleString()}
      </span>
    ),
  },
];

export default function ClassificationPage() {
  const [label, setLabel] = useState("");
  const [reviewRoute, setReviewRoute] = useState("");
  const navigate = useNavigate();

  const { data } = useQuery({
    queryKey: ["jobs", label, reviewRoute],
    queryFn: () =>
      fetchJobsPage({ label: label || undefined, reviewRoute: reviewRoute || undefined }),
  });

  return (
    <div className="p-6">
      <h1 className="mb-6 text-xl font-bold text-[var(--color-text)]">Classification</h1>
      <div className="mb-4 flex gap-2">
        <input
          placeholder="Filter by label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2 font-mono text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-faint)]"
        />
        <input
          placeholder="Filter by review route"
          value={reviewRoute}
          onChange={(e) => setReviewRoute(e.target.value)}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2 font-mono text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-faint)]"
        />
      </div>
      <DataTable
        columns={COLUMNS}
        rows={data?.items ?? []}
        rowKey={(row) => row.jobId}
        onRowClick={(row) => navigate(`/documents/${row.jobId}`)}
      />
    </div>
  );
}

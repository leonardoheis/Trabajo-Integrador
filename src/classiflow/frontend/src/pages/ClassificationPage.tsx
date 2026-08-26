import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { fetchJobsPage, type ClassificationSummary, type SortField } from "../api/documents";
import DataTable, { type Column } from "../components/DataTable";
import StatusBadge from "../components/StatusBadge";

const COLUMNS: Column<ClassificationSummary>[] = [
  { header: "Filename", sortKey: "filename", render: (row) => row.filename },
  { header: "Label", sortKey: "label", render: (row) => row.label ?? "—" },
  { header: "Review Route", render: (row) => <StatusBadge status={row.reviewRoute} /> },
  {
    header: "Confidence",
    sortKey: "confidence",
    render: (row) => (
      <span className="font-mono text-[var(--color-text-muted)]">
        {row.confidence.toFixed(2)}
      </span>
    ),
  },
  { header: "Judged", render: (row) => (row.judgedByLlm ? "Yes" : "No") },
  {
    header: "Created",
    sortKey: "createdAt",
    render: (row) => (
      <span className="font-mono text-xs text-[var(--color-text-faint)]">
        {new Date(row.createdAt).toLocaleString()}
      </span>
    ),
  },
];

const PAGE_SIZE_OPTIONS = [5, 10, 15, 20, 50] as const;

export default function ClassificationPage() {
  const [label, setLabel] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZE_OPTIONS[1]);
  const [sortField, setSortField] = useState<SortField | undefined>(undefined);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const navigate = useNavigate();

  const { data } = useQuery({
    queryKey: ["jobs", label, page, pageSize, sortField, sortDir],
    queryFn: () =>
      fetchJobsPage({
        label: label || undefined,
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
    <div className="p-6">
      <h1 className="mb-6 text-xl font-bold text-[var(--color-text)]">Classification</h1>
      <div className="mb-4">
        <input
          placeholder="Filter by label"
          value={label}
          onChange={(e) => {
            setLabel(e.target.value);
            setPage(1);
          }}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2 font-mono text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-faint)]"
        />
      </div>
      <DataTable
        columns={COLUMNS}
        rows={data?.items ?? []}
        rowKey={(row) => row.jobId}
        onRowClick={(row) => navigate(`/documents/${row.jobId}`)}
        sort={sortField ? { key: sortField, dir: sortDir } : undefined}
        onSortChange={handleSortChange}
      />
      <div className="mt-4 flex items-center justify-between font-mono text-xs text-[var(--color-text-faint)]">
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

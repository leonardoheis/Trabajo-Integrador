import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { fetchAuditPage, type AuditRecordItem } from "../api/audit";
import DataTable, { type Column } from "../components/DataTable";

const COLUMNS: Column<AuditRecordItem>[] = [
  { header: "Job", render: (r) => r.jobId },
  { header: "Node", render: (r) => r.node },
  { header: "Event", render: (r) => r.event },
  { header: "Timestamp", render: (r) => new Date(r.timestamp).toLocaleString() },
  { header: "Duration (ms)", render: (r) => r.durationMs ?? "—" },
];

export default function AuditLogPage() {
  const [jobId, setJobId] = useState("");
  const navigate = useNavigate();

  const { data } = useQuery({
    queryKey: ["audit", jobId],
    queryFn: () => fetchAuditPage({ jobId: jobId || undefined }),
  });

  return (
    <div className="p-6">
      <h1 className="mb-4 text-xl font-semibold">Audit Log</h1>
      <input
        placeholder="Filter by job ID"
        value={jobId}
        onChange={(e) => setJobId(e.target.value)}
        className="mb-4 rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2 text-sm"
      />
      <DataTable
        columns={COLUMNS}
        rows={data?.items ?? []}
        rowKey={(r) => `${r.jobId}-${r.node}-${r.timestamp}`}
        onRowClick={(r) => navigate(`/documents/${r.jobId}`)}
      />
    </div>
  );
}

import { apiFetch } from "./auth";

export interface AuditRecordItem {
  jobId: string;
  node: string;
  event: string;
  timestamp: string;
  durationMs: number | null;
  detail: Record<string, unknown> | null;
}

export interface AuditPage {
  items: AuditRecordItem[];
  total: number;
  page: number;
  pageSize: number;
}

export async function fetchAuditPage(params: {
  jobId?: string;
  node?: string;
}): Promise<AuditPage> {
  const query = new URLSearchParams();
  if (params.jobId) query.set("jobId", params.jobId);
  if (params.node) query.set("node", params.node);

  const response = await apiFetch(`/audit?${query.toString()}`);
  if (!response.ok) {
    throw new Error(`GET /audit failed: ${response.status}`);
  }
  return response.json();
}

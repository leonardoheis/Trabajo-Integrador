import { apiFetch } from "./auth";

export interface JobSummary {
  jobId: string;
  filename: string;
  status: string;
  createdAt: string;
  updatedAt: string;
}

export interface TimelineEntry {
  node: string;
  status: string;
  passed: boolean | null;
  detail: Record<string, unknown> | null;
  timestamp: string;
  durationMs: number | null;
}

export async function fetchRunningJobs(): Promise<JobSummary[]> {
  const response = await apiFetch("/pipeline/jobs?status=running");
  if (!response.ok) {
    throw new Error(`GET /pipeline/jobs failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchJobTimeline(jobId: string): Promise<TimelineEntry[]> {
  const response = await apiFetch(`/pipeline/jobs/${jobId}/timeline`);
  if (!response.ok) {
    throw new Error(`GET /pipeline/jobs/${jobId}/timeline failed: ${response.status}`);
  }
  return response.json();
}

export async function pipelineWarmup(): Promise<void> {
  await apiFetch("/pipeline/warmup", { method: "POST" });
}

export async function discardJob(jobId: string): Promise<void> {
  const response = await apiFetch(`/pipeline/jobs/${jobId}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`DELETE /pipeline/jobs/${jobId} failed: ${response.status}`);
  }
}

export async function uploadDocuments(files: File[]): Promise<string[]> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  const response = await apiFetch("/pipeline/ingest-bulk", { method: "POST", body: formData });
  if (!response.ok) {
    throw new Error(`POST /pipeline/ingest-bulk failed: ${response.status}`);
  }
  const body = (await response.json()) as { jobIds: string[] };
  return body.jobIds;
}

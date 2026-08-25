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

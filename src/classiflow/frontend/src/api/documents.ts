import { apiFetch } from "./auth";

export interface ClassificationSummary {
  jobId: string;
  filename: string;
  status: string;
  label: string | null;
  reviewRoute: string;
  confidence: number;
  judgedByLlm: boolean;
  createdAt: string;
  indexed: boolean;
}

export interface JobsPage {
  items: ClassificationSummary[];
  total: number;
  page: number;
  pageSize: number;
}

export interface JobDetailResponse {
  job: { jobId: string; filename: string; status: string; createdAt: string };
  enriched: {
    cleanedText: string;
    rawText: string | null;
    entities: Record<string, unknown>;
    metadata: Record<string, unknown>;
  } | null;
  classification: {
    label: string | null;
    confidence: number;
    allScores: Record<string, unknown>;
    secondOpinionLabel: string | null;
    secondOpinionConfidence: number;
    classifierDisagreement: boolean;
    oodMetrics: Record<string, unknown> | null;
    svmScores: Record<string, unknown>;
    svmAgreesWithPrediction: boolean;
    reviewRoute: string;
    smells: string[];
    riskScore: number;
    smellReviewSuggested: boolean;
    foreignMunicipality: string | null;
    judgedByLlm: boolean;
    judgeFinalLabel: string | null;
    judgeReasoning: string | null;
    storedPath: string | null;
    humanOverridden: boolean;
    originalLabel: string | null;
    expectedLabel: string | null;
  } | null;
  audit: {
    jobId: string;
    node: string;
    event: string;
    timestamp: string;
    durationMs: number | null;
    detail: Record<string, unknown> | null;
  }[];
}

export type SortField = "filename" | "label" | "confidence" | "createdAt" | "indexed";
export type SortDir = "asc" | "desc";

export async function fetchJobsPage(params: {
  search?: string;
  reviewRoute?: string;
  page?: number;
  pageSize?: number;
  sort?: SortField;
  sortDir?: SortDir;
}): Promise<JobsPage> {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.reviewRoute) query.set("reviewRoute", params.reviewRoute);
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("pageSize", String(params.pageSize));
  if (params.sort) query.set("sort", params.sort);
  if (params.sortDir) query.set("sortDir", params.sortDir);

  const response = await apiFetch(`/jobs?${query.toString()}`);
  if (!response.ok) {
    throw new Error(`GET /jobs failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchJobDetail(jobId: string): Promise<JobDetailResponse> {
  const response = await apiFetch(`/jobs/${jobId}/detail`);
  if (!response.ok) {
    throw new Error(`GET /jobs/${jobId}/detail failed: ${response.status}`);
  }
  return response.json();
}

export function documentFileUrl(jobId: string): string {
  return `/documents/${jobId}/file`;
}

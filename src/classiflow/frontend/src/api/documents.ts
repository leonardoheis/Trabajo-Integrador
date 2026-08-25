import { apiFetch } from "./auth";

export interface ClassificationSummary {
  jobId: string;
  filename: string;
  label: string | null;
  reviewRoute: string;
  confidence: number;
  judgedByLlm: boolean;
  createdAt: string;
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

export async function fetchJobsPage(params: {
  label?: string;
  reviewRoute?: string;
  page?: number;
}): Promise<JobsPage> {
  const query = new URLSearchParams();
  if (params.label) query.set("label", params.label);
  if (params.reviewRoute) query.set("reviewRoute", params.reviewRoute);
  if (params.page) query.set("page", String(params.page));

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

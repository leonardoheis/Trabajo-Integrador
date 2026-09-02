import { apiFetch } from "./auth";

export interface ReviewQueueItem {
  jobId: string;
  label: string | null;
  confidence: number;
  secondOpinionLabel: string | null;
  reviewRoute: string;
  smells: string[];
  riskScore: number;
  smellReviewSuggested: boolean;
  foreignMunicipality: string | null;
  judgedByLlm: boolean;
  judgeFinalLabel: string | null;
  judgeReasoning: string | null;
  createdAt: string;
}

export async function fetchReviewQueue(): Promise<ReviewQueueItem[]> {
  const response = await apiFetch("/classification/review-queue");
  if (!response.ok) {
    throw new Error(`GET /classification/review-queue failed: ${response.status}`);
  }
  return response.json();
}

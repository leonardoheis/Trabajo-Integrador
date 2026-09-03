import { apiFetch } from "./auth";

export interface CategoryMetrics {
  category: string;
  support: number;
  predicted: number;
  correct: number;
  precision: number;
  recall: number;
  f1: number;
}

export interface Miss {
  jobId: string;
  filename: string;
  expected: string;
  predicted: string;
  reviewRoute: string;
  caughtBySafetyNet: boolean;
}

export interface AccuracyReport {
  totalJobs: number;
  neverClassified: number;
  neverClassifiedByStatus: Record<string, number>;
  totalClassified: number;
  labelled: number;
  correct: number;
  wrongCaught: number;
  wrongUncaught: number;
  strictAccuracy: number;
  safeguardedAccuracy: number;
  perCategory: CategoryMetrics[];
  confusion: Record<string, Record<string, number>>;
  misses: Miss[];
  unevaluatedCategories: string[];
}

export async function fetchAccuracyMetrics(): Promise<AccuracyReport> {
  const response = await apiFetch("/classification/metrics");
  if (!response.ok) {
    throw new Error(`GET /classification/metrics failed: ${response.status}`);
  }
  return response.json();
}

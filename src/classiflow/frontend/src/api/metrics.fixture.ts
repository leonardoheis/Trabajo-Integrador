import type { AccuracyReport } from "./metrics";

// A real GET /classification/metrics response, pinned with `satisfies` so that renaming
// or removing a field in AccuracyReport fails tsc. The matching backend guard is
// test_response_schema_matches_the_frontend_contract, which pins what the API publishes.
export const accuracyReportFixture = {
  totalJobs: 77,
  neverClassified: 9,
  neverClassifiedByStatus: { rejected: 8, failed: 1 },
  totalClassified: 68,
  labelled: 55,
  correct: 45,
  wrongCaught: 10,
  wrongUncaught: 0,
  strictAccuracy: 0.8181818181818182,
  safeguardedAccuracy: 1.0,
  perCategory: [
    {
      category: "decretos",
      support: 14,
      predicted: 22,
      correct: 14,
      precision: 0.6363636363636364,
      recall: 1.0,
      f1: 0.7777777777777778,
    },
    {
      category: "boletines",
      support: 11,
      predicted: 9,
      correct: 9,
      precision: 1.0,
      recall: 0.8181818181818182,
      f1: 0.9,
    },
  ],
  confusion: {
    decretos: { decretos: 14 },
    boletines: { boletines: 9, decretos: 2 },
  },
  misses: [
    {
      jobId: "9f8853d4-1cb4-4fbe-9077-045357591c77",
      filename: "boletin_2065_2026.pdf",
      expected: "boletines",
      predicted: "decretos",
      reviewRoute: "human_review",
      caughtBySafetyNet: true,
    },
  ],
  unevaluatedCategories: ["compendios_de_boletines"],
  unknownLabels: [],
} satisfies AccuracyReport;

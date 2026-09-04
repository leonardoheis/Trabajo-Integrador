import { describe, expect, it } from "vitest";
import { accuracyReportFixture } from "./metrics.fixture";

// The fixture's `satisfies AccuracyReport` is the real guard -- it fails at compile time
// if the interface drifts. These assertions keep it imported (so tsc checks it) and pin
// the invariants the Metrics page relies on.
describe("AccuracyReport contract", () => {
  it("reports the funnel from ingested to scoreable", () => {
    const report = accuracyReportFixture;
    expect(report.totalJobs - report.neverClassified).toBe(report.totalClassified);
    expect(report.labelled).toBeLessThanOrEqual(report.totalClassified);
  });

  it("splits every miss into caught or filed", () => {
    const report = accuracyReportFixture;
    expect(report.correct + report.wrongCaught + report.wrongUncaught).toBe(report.labelled);
  });

  it("counts each status in the never-classified breakdown", () => {
    const byStatus = Object.values(accuracyReportFixture.neverClassifiedByStatus);
    const total = byStatus.reduce((sum, count) => sum + count, 0);
    expect(total).toBe(accuracyReportFixture.neverClassified);
  });
});

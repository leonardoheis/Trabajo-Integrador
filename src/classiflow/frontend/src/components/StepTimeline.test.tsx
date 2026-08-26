import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StepTimeline from "./StepTimeline";
import type { TimelineEntry } from "../api/jobs";

function entry(node: string, status: string, timestamp: string): TimelineEntry {
  return {
    node,
    status,
    passed: status === "passed" ? true : status === "failed" ? false : null,
    detail: null,
    timestamp,
    durationMs: status === "passed" ? 50 : null,
  };
}

const INGESTA_DONE: TimelineEntry[] = [
  entry("node1_file_reception", "passed", "2026-08-24T10:00:00Z"),
  entry("node2_format_validation", "passed", "2026-08-24T10:00:01Z"),
];

describe("StepTimeline", () => {
  it("shows a waiting message when there are no entries yet", () => {
    render(<StepTimeline entries={[]} />);
    expect(screen.getByText("Waiting for the first step…")).toBeInTheDocument();
  });

  it("renders a phase name for a completed phase", () => {
    render(<StepTimeline entries={INGESTA_DONE} />);
    expect(screen.getByText("Ingesta")).toBeInTheDocument();
  });

  it("condensed mode: collapses a completed phase to a summary, hiding its individual step names", () => {
    render(<StepTimeline entries={INGESTA_DONE} mode="condensed" />);
    expect(screen.getByText("Ingesta")).toBeInTheDocument();
    expect(screen.queryByText("node1_file_reception")).not.toBeInTheDocument();
    expect(screen.queryByText("node2_format_validation")).not.toBeInTheDocument();
  });

  it("condensed mode: expands the live (non-terminal) phase to show its individual steps", () => {
    const entries: TimelineEntry[] = [
      ...INGESTA_DONE,
      entry("classification_primary_classifier", "passed", "2026-08-24T10:00:02Z"),
      entry("classification_second_opinion", "started", "2026-08-24T10:00:03Z"),
    ];
    render(<StepTimeline entries={entries} mode="condensed" />);
    expect(screen.getByText("Classification")).toBeInTheDocument();
    expect(screen.getByText("classification_second_opinion")).toBeInTheDocument();
    expect(screen.getByText("started…")).toBeInTheDocument();
    // The already-done sibling phase stays collapsed:
    expect(screen.queryByText("node1_file_reception")).not.toBeInTheDocument();
  });

  it("expanded mode: shows every phase's individual steps, including completed ones", () => {
    render(<StepTimeline entries={INGESTA_DONE} mode="expanded" />);
    expect(screen.getByText("node1_file_reception")).toBeInTheDocument();
    expect(screen.getByText("node2_format_validation")).toBeInTheDocument();
  });

  it("defaults to condensed mode when mode is omitted", () => {
    render(<StepTimeline entries={INGESTA_DONE} />);
    expect(screen.queryByText("node1_file_reception")).not.toBeInTheDocument();
  });
});

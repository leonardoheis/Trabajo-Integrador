import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StepTimeline from "./StepTimeline";
import type { TimelineEntry } from "../api/jobs";

const BACKFILLED: TimelineEntry[] = [
  {
    node: "node1_file_reception",
    status: "passed",
    passed: true,
    detail: null,
    timestamp: "2026-08-24T10:00:00Z",
    durationMs: 50,
  },
];

describe("StepTimeline", () => {
  it("renders backfilled steps", () => {
    render(<StepTimeline entries={BACKFILLED} />);
    expect(screen.getByText("node1_file_reception")).toBeInTheDocument();
  });

  it("renders both a backfilled entry and a separately-provided completed entry", () => {
    const completed: TimelineEntry = {
      node: "node2_format_validation",
      status: "passed",
      passed: true,
      detail: null,
      timestamp: "2026-08-24T10:00:05Z",
      durationMs: 30,
    };
    render(<StepTimeline entries={[...BACKFILLED, completed]} />);
    expect(screen.getByText("node1_file_reception")).toBeInTheDocument();
    expect(screen.getByText("node2_format_validation")).toBeInTheDocument();
  });

  it("expands the most recent step with its live status when it hasn't reached a terminal state", () => {
    const inProgress: TimelineEntry = {
      node: "classification_llm_judge",
      status: "started",
      passed: null,
      detail: null,
      timestamp: "2026-08-24T10:00:10Z",
      durationMs: null,
    };
    render(<StepTimeline entries={[...BACKFILLED, inProgress]} />);
    expect(screen.getByText("node1_file_reception")).toBeInTheDocument();
    expect(screen.getByText("classification_llm_judge")).toBeInTheDocument();
    expect(screen.getByText("started…")).toBeInTheDocument();
  });

  it("shows a waiting message when there are no entries yet", () => {
    render(<StepTimeline entries={[]} />);
    expect(screen.getByText("Waiting for the first step…")).toBeInTheDocument();
  });
});

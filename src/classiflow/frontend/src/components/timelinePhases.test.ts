import { describe, it, expect } from "vitest";
import { groupByPhase } from "./timelinePhases";
import type { TimelineEntry } from "../api/jobs";

function entry(node: string, status = "passed"): TimelineEntry {
  return {
    node,
    status,
    passed: status === "passed" ? true : status === "failed" ? false : null,
    detail: null,
    timestamp: "2026-08-25T10:00:00Z",
    durationMs: 50,
  };
}

describe("groupByPhase", () => {
  it("groups ingesta nodes (node1-node4) under Ingesta", () => {
    const phases = groupByPhase([
      entry("node1_file_reception"),
      entry("node2_format_validation"),
      entry("node3_content_validation"),
      entry("node4_duplicate_control"),
    ]);
    expect(phases).toHaveLength(1);
    expect(phases[0].name).toBe("Ingesta");
    expect(phases[0].entries).toHaveLength(4);
  });

  it("groups enrichment_* nodes under Enrichment", () => {
    const phases = groupByPhase([
      entry("enrichment_text_cleaner"),
      entry("enrichment_entity_extractor"),
    ]);
    expect(phases).toHaveLength(1);
    expect(phases[0].name).toBe("Enrichment");
  });

  it("groups classification_* nodes (except routing) under Classification", () => {
    const phases = groupByPhase([
      entry("classification_primary_classifier"),
      entry("classification_second_opinion"),
      entry("classification_llm_judge"),
    ]);
    expect(phases).toHaveLength(1);
    expect(phases[0].name).toBe("Classification");
  });

  it("puts classification_routing under its own Routing phase, not Classification", () => {
    const phases = groupByPhase([
      entry("classification_primary_classifier"),
      entry("classification_routing"),
    ]);
    expect(phases).toHaveLength(2);
    expect(phases[0].name).toBe("Classification");
    expect(phases[0].entries).toHaveLength(1);
    expect(phases[1].name).toBe("Routing");
    expect(phases[1].entries).toHaveLength(1);
  });

  it("returns phases in fixed Ingesta/Enrichment/Classification/Routing order regardless of input order", () => {
    const phases = groupByPhase([
      entry("classification_routing"),
      entry("node1_file_reception"),
      entry("enrichment_text_cleaner"),
    ]);
    expect(phases.map((p) => p.name)).toEqual(["Ingesta", "Enrichment", "Routing"]);
  });

  it("omits a phase entirely when no entry maps to it", () => {
    const phases = groupByPhase([entry("node1_file_reception"), entry("node2_format_validation", "failed")]);
    expect(phases).toHaveLength(1);
    expect(phases[0].name).toBe("Ingesta");
  });

  it("returns an empty array for no entries", () => {
    expect(groupByPhase([])).toEqual([]);
  });
});

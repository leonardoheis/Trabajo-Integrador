import type { TimelineEntry } from "../api/jobs";

export type PhaseName = "Ingesta" | "Enrichment" | "Classification" | "Routing";

export interface Phase {
  name: PhaseName;
  entries: TimelineEntry[];
}

const PHASE_ORDER: PhaseName[] = ["Ingesta", "Enrichment", "Classification", "Routing"];

function phaseFor(node: string): PhaseName {
  if (node === "classification_routing") {
    return "Routing";
  }
  if (node.startsWith("classification_")) {
    return "Classification";
  }
  if (node.startsWith("enrichment_")) {
    return "Enrichment";
  }
  // node1_file_reception..node4_duplicate_control, and the extraction step
  // (unprefixed "extraction") all belong to Stage 1 ingesta.
  return "Ingesta";
}

export function groupByPhase(entries: TimelineEntry[]): Phase[] {
  const byPhase = new Map<PhaseName, TimelineEntry[]>();
  for (const entry of entries) {
    const name = phaseFor(entry.node);
    const bucket = byPhase.get(name) ?? [];
    bucket.push(entry);
    byPhase.set(name, bucket);
  }
  return PHASE_ORDER.filter((name) => byPhase.has(name)).map((name) => ({
    name,
    entries: byPhase.get(name)!,
  }));
}

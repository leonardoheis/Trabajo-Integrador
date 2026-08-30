import { apiFetch } from "./auth";

export interface DocumentKbRecord {
  sha256: string;
  filename: string;
  docType: string | null;
  number: string | null;
  year: string | null;
  chunkCount: number;
  indexedAt: string;
}

export interface DocumentKbResponse {
  documentKb: DocumentKbRecord | null;
}

export async function fetchDocumentKb(jobId: string): Promise<DocumentKbResponse> {
  const response = await apiFetch(`/knowledge/documents/${jobId}`);
  if (!response.ok) {
    throw new Error(`GET /knowledge/documents/${jobId} failed: ${response.status}`);
  }
  return response.json();
}

export async function indexDocument(jobId: string): Promise<DocumentKbResponse> {
  const response = await apiFetch(`/knowledge/documents/${jobId}/index`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`POST /knowledge/documents/${jobId}/index failed: ${response.status}`);
  }
  return response.json();
}

export interface SynchronizeKbResult {
  indexedJobIds: string[];
  skippedCount: number;
}

export async function synchronizeKb(): Promise<SynchronizeKbResult> {
  const response = await apiFetch("/knowledge/synchronize-kb", { method: "POST" });
  if (!response.ok) {
    throw new Error(`POST /knowledge/synchronize-kb failed: ${response.status}`);
  }
  return response.json();
}

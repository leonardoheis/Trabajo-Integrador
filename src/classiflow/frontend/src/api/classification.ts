import { apiFetch } from "./auth";

export async function submitReclassification(
  jobId: string,
  label: string,
  notes: string,
): Promise<void> {
  const response = await apiFetch(`/classification/${jobId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label, notes }),
  });
  if (!response.ok) {
    throw new Error(`POST /classification/${jobId}/decision failed: ${response.status}`);
  }
}

export const DOCUMENT_CATEGORIES = [
  "boletines",
  "compendios_de_boletines",
  "convenios",
  "declaraciones_concejo_municipal",
  "decreto_ordenanzas",
  "decretos",
  "decretos_concejo_municipal",
  "ordenanzas",
  "otro",
  "resoluciones",
  "resoluciones_concejo_municipal",
] as const;

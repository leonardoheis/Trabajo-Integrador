export enum DocumentType {
  INVOICE = 'INVOICE',
  CONTRACT = 'CONTRACT',
  REPORT = 'REPORT',
  IDENTIFICATION = 'IDENTIFICATION',
  FORM = 'FORM',
  LETTER = 'LETTER',
  RECEIPT = 'RECEIPT',
  OTHER = 'OTHER',
}

export enum JobStatus {
  PENDING = 'PENDING',
  INGESTING = 'INGESTING',
  ANALYZING = 'ANALYZING',
  ORCHESTRATING = 'ORCHESTRATING',
  ROUTING = 'ROUTING',
  DONE = 'DONE',
  FAILED = 'FAILED',
}

export interface AzureAnalysisResult {
  document_type: DocumentType | null
  confidence: number
  extracted_fields: Record<string, string | number | boolean | null>
  tags: string[]
  language: string | null
  page_count: number | null
  raw_response: Record<string, unknown> | null
}

export interface JobRecord {
  job_id: string
  filename: string
  status: JobStatus
  document_type: DocumentType | null
  created_at: string
  updated_at: string
  error_message: string | null
  analysis_result: AzureAnalysisResult | null
  output_path: string | null
}

export interface AuditEntry {
  id: number
  job_id: string
  event: string
  detail: Record<string, unknown> | null
  timestamp: string
}

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    INVOICE = "invoice"
    CONTRACT = "contract"
    TAX_FORM = "tax_form"
    REPORT = "report"
    UNKNOWN = "unknown"


class JobStatus(str, Enum):
    PENDING = "pending"
    INGESTING = "ingesting"
    ANALYZING = "analyzing"
    ORCHESTRATING = "orchestrating"
    ROUTING = "routing"
    DONE = "done"
    FAILED = "failed"


class IngestionResult(BaseModel):
    filename: str
    format: str
    size_bytes: int
    text_preview: str = ""


class AzureAnalysisResult(BaseModel):
    doc_type: DocumentType
    confidence: float
    fields: dict[str, Any] = Field(default_factory=dict)
    raw_response: dict[str, Any] = Field(default_factory=dict)


class JobRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    result: Optional[AzureAnalysisResult] = None
    output_path: Optional[str] = None
    error: Optional[str] = None


class AuditEntry(BaseModel):
    job_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    event: str
    details: dict[str, Any] = Field(default_factory=dict)

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from config import settings
from models import AuditEntry
from storage import get_audit_log

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/audit", response_model=list[AuditEntry])
async def list_audit_entries(limit: int = 100) -> list[AuditEntry]:
    """Return the most recent N audit log entries (in-memory)."""
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    return await get_audit_log(limit=limit)


@router.get("/audit/download")
async def download_audit_log() -> FileResponse:
    """Download the full audit.jsonl file from disk."""
    audit_file: Path = settings.OUTPUT_BASE_DIR / "audit.jsonl"
    if not audit_file.exists():
        raise HTTPException(
            status_code=404,
            detail="audit.jsonl not found. No documents have been processed yet.",
        )
    return FileResponse(
        path=str(audit_file),
        media_type="application/x-ndjson",
        filename="audit.jsonl",
    )

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from config import settings
from models import AuditEntry, DocumentType
from storage import append_audit

logger = logging.getLogger(__name__)

_FOLDER_MAP: dict[DocumentType, str] = {
    DocumentType.INVOICE: "invoices",
    DocumentType.CONTRACT: "contracts",
    DocumentType.TAX_FORM: "tax_returns",
    DocumentType.REPORT: "reports",
    DocumentType.UNKNOWN: "review",
}


async def route(
    job_id: str,
    doc_type: DocumentType,
    confidence: float,
    file_bytes: bytes,
    filename: str,
    metadata: dict[str, Any],
) -> str:
    """Save the file to the appropriate output folder and write an audit entry.

    Returns the absolute output path as a string.
    """
    # Low-confidence documents always go to review
    if confidence < settings.CONFIDENCE_THRESHOLD:
        folder_name = "review"
        logger.info(
            "Job %s routed to 'review' due to low confidence (%.4f < %.4f).",
            job_id,
            confidence,
            settings.CONFIDENCE_THRESHOLD,
        )
    else:
        folder_name = _FOLDER_MAP.get(doc_type, "review")
        logger.info(
            "Job %s routed to '%s' (doc_type=%s, confidence=%.4f).",
            job_id,
            folder_name,
            doc_type,
            confidence,
        )

    output_dir = settings.OUTPUT_BASE_DIR / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Avoid collisions by prefixing with job_id
    safe_filename = f"{job_id[:8]}_{filename}"
    output_path = output_dir / safe_filename

    async with aiofiles.open(output_path, "wb") as fh:
        await fh.write(file_bytes)

    logger.info("File saved to '%s'.", output_path)

    # Write audit entry to in-memory log
    entry = AuditEntry(
        job_id=job_id,
        event="file_routed",
        details={
            "output_path": str(output_path),
            "folder": folder_name,
            "doc_type": doc_type,
            "confidence": confidence,
            **{k: metadata.get(k) for k in ("tags", "language", "page_count", "has_tables")},
        },
    )
    await append_audit(entry)

    # Also append to JSONL audit file on disk
    audit_file = settings.OUTPUT_BASE_DIR / "audit.jsonl"
    audit_record = {
        "job_id": job_id,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "event": "file_routed",
        "filename": filename,
        "output_path": str(output_path),
        "folder": folder_name,
        "doc_type": doc_type,
        "confidence": confidence,
        "metadata": metadata,
    }
    async with aiofiles.open(audit_file, "a", encoding="utf-8") as fh:
        await fh.write(json.dumps(audit_record) + "\n")

    return str(output_path)

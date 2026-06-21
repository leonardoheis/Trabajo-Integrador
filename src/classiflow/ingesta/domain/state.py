from .base import BaseEntity
from .results import (
    ContentValidationResult,
    DuplicateControlResult,
    FileReceptionResult,
    FormatValidationResult,
)


class JobState(BaseEntity):
    job_id: str | None = None
    filename: str | None = None
    file_bytes: bytes | None = None
    reception: FileReceptionResult | None = None
    format_validation: FormatValidationResult | None = None
    content_validation: ContentValidationResult | None = None
    duplicate_control: DuplicateControlResult | None = None
    final_status: str | None = None
    rejection_reason: str | None = None

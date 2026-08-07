from typing import TypedDict

from .results import (
    ContentValidationResult,
    DuplicateControlResult,
    FileReceptionResult,
    FormatValidationResult,
)


class _JobStateRequired(TypedDict):
    job_id: str
    filename: str
    file_bytes: bytes | None


class JobState(_JobStateRequired, total=False):
    text: str
    reception: FileReceptionResult | None
    format_validation: FormatValidationResult | None
    content_validation: ContentValidationResult | None
    duplicate_control: DuplicateControlResult | None
    final_status: str | None
    rejection_reason: str | None

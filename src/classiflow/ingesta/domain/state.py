from typing import TypedDict

from .results import (
    ContentValidationResult,
    DuplicateControlResult,
    ExtractionResult,
    FileReceptionResult,
    FormatValidationResult,
)


class _JobStateRequired(TypedDict):
    job_id: str
    filename: str
    file_bytes: bytes | None


class JobState(_JobStateRequired, total=False):
    text: str
    reception: FileReceptionResult
    format_validation: FormatValidationResult
    extraction: ExtractionResult
    content_validation: ContentValidationResult
    duplicate_control: DuplicateControlResult
    final_status: str
    rejection_reason: str

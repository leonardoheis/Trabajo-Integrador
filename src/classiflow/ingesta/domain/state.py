from typing import TypedDict

from classiflow.ingesta.domain.results import (
    ContentValidationResult,
    DuplicateControlResult,
    FileReceptionResult,
    FormatValidationResult,
)


class JobState(TypedDict, total=False):
    job_id: str
    filename: str
    file_bytes: bytes
    reception: FileReceptionResult
    format_validation: FormatValidationResult
    content_validation: ContentValidationResult
    duplicate_control: DuplicateControlResult
    final_status: str
    rejection_reason: str

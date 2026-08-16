from typing import TypedDict

from .results import (
    ContentValidationResult,
    DuplicateControlResult,
    FileReceptionResult,
    FormatValidationResult,
    KnowledgeIndexingResult,
)


class _JobStateRequired(TypedDict):
    job_id: str
    filename: str
    file_bytes: bytes | None


class JobState(_JobStateRequired, total=False):
    text: str
    reception: FileReceptionResult
    format_validation: FormatValidationResult
    content_validation: ContentValidationResult
    duplicate_control: DuplicateControlResult
    knowledge_indexing: KnowledgeIndexingResult
    final_status: str
    rejection_reason: str

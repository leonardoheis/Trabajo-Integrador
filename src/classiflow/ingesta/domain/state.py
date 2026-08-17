from typing import TypedDict

from classiflow.domain.base import BaseEntity

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


class NodeUpdate(BaseEntity):
    """Typed construction for a coordinator node's partial JobState update -- every
    field optional since each node only ever sets a subset. coordinator.py's `_dump()`
    helper turns this into the plain dict LangGraph actually merges into state; only
    `None` fields are excluded, so a legitimately-set empty string (e.g.
    rejection_reason="") survives."""

    text: str | None = None
    reception: FileReceptionResult | None = None
    format_validation: FormatValidationResult | None = None
    extraction: ExtractionResult | None = None
    content_validation: ContentValidationResult | None = None
    duplicate_control: DuplicateControlResult | None = None
    final_status: str | None = None
    rejection_reason: str | None = None

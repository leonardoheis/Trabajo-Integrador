from enum import Enum

from classiflow.domain.base import BaseEntity


class FormatDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    MANUAL_REVIEW = "manual_review"


class ExtractionResult(BaseEntity):
    # passed/rejection_reason default to the "always succeeds" values -- extraction
    # never rejects a document (that judgment stays in node3's validate()), these
    # fields exist only so ExtractionStep fits the same _StepResult shape node1-4 use
    # for PipelineService._persist_steps.
    passed: bool = True
    text: str = ""
    extractor_used: str = ""
    char_count: int = 0
    rejection_reason: str = ""


class FileReceptionResult(BaseEntity):
    passed: bool
    sha256: str = ""
    detected_mime: str = ""
    file_size_bytes: int = 0
    rejection_reason: str = ""


class FormatValidationResult(BaseEntity):
    passed: bool
    decision: FormatDecision
    used_slm: bool = False
    rejection_reason: str = ""


class ContentValidationResult(BaseEntity):
    passed: bool
    detected_language: str = ""
    char_count: int = 0
    needs_agent_review: bool = False
    requires_ocr: bool = False
    rejection_reason: str = ""
    confidence: float = 0.0


class DuplicateControlResult(BaseEntity):
    passed: bool
    is_duplicate: bool = False
    duplicate_type: str = ""
    similarity_score: float = 0.0
    rejection_reason: str = ""

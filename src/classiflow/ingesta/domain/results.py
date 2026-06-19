from enum import Enum

from pydantic import BaseModel


class FormatDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    MANUAL_REVIEW = "manual_review"


class FileReceptionResult(BaseModel):
    passed: bool
    sha256: str = ""
    detected_mime: str = ""
    file_size_bytes: int = 0
    rejection_reason: str = ""


class FormatValidationResult(BaseModel):
    passed: bool
    decision: FormatDecision
    used_slm: bool = False
    rejection_reason: str = ""


class ContentValidationResult(BaseModel):
    passed: bool
    detected_language: str = ""
    char_count: int = 0
    needs_agent_review: bool = False
    rejection_reason: str = ""


class DuplicateControlResult(BaseModel):
    passed: bool
    is_duplicate: bool = False
    duplicate_type: str = ""
    similarity_score: float = 0.0
    rejection_reason: str = ""

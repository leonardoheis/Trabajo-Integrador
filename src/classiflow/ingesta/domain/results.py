from enum import Enum

from classiflow.domain.base import BaseEntity


class FormatDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    MANUAL_REVIEW = "manual_review"


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


class KnowledgeIndexingResult(BaseEntity):
    # `passed` stays True even when indexing fails: the document already cleared every
    # validation gate, so a knowledge-base problem must not retroactively reject it.
    # `indexed` is the field that says whether it is searchable.
    passed: bool
    indexed: bool = False
    chunk_count: int = 0
    doc_type: str = ""
    number: str = ""
    year: str = ""
    subject: str = ""
    download_url: str = ""
    rejection_reason: str = ""

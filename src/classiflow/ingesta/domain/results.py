from enum import Enum

from classiflow.domain.base import BaseEntity


class FormatDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    MANUAL_REVIEW = "manual_review"
    # Internal-only: rule_based_check()'s signal to defer to the SLM -- never a value
    # the SLM itself returns (see prompts/format_validation.py's prompt, which only
    # asks it to choose accept/reject/manual_review), so it never reaches a final
    # FormatValidationResult.decision.
    SLM_ESCALATE = "slm_escalate"


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

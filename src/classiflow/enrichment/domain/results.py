from pydantic import Field

from classiflow.domain.base import BaseEntity


class TextCleaningResult(BaseEntity):
    cleaned_text: str = ""


class EntityExtractionResult(BaseEntity):
    doc_type_hint: str | None = None
    number: str | None = None
    year: int | None = None
    issuing_body: str | None = None
    signatories: list[str] = Field(default_factory=list)
    article_count: int | None = None


class MetadataEnrichmentResult(BaseEntity):
    source: str = ""
    filename: str = ""
    language: str = ""
    sha256: str = ""
    stage2_extractor_used: str = ""

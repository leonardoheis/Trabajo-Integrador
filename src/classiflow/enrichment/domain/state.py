from typing import TypedDict

from classiflow.domain.base import BaseEntity

from .results import EntityExtractionResult, MetadataEnrichmentResult, TextCleaningResult


class _EnrichmentStateRequired(TypedDict):
    job_id: str
    filename: str
    text: str
    language: str
    sha256: str
    stage2_extractor_used: str


class EnrichmentState(_EnrichmentStateRequired, total=False):
    cleaned_text: str
    cleaning: TextCleaningResult
    entities: EntityExtractionResult
    metadata: MetadataEnrichmentResult


class EnrichmentUpdate(BaseEntity):
    """Typed construction for an enrichment coordinator node's partial
    EnrichmentState update — mirrors ingesta/domain/state.py's NodeUpdate pattern."""

    cleaned_text: str | None = None
    cleaning: TextCleaningResult | None = None
    entities: EntityExtractionResult | None = None
    metadata: MetadataEnrichmentResult | None = None

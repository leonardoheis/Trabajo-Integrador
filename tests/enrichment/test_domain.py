import pytest

from classiflow.enrichment.domain.results import (
    EntityExtractionResult,
    MetadataEnrichmentResult,
    TextCleaningResult,
)
from classiflow.enrichment.domain.state import EnrichmentUpdate
from classiflow.enrichment.exceptions import EntityExtractionFailedError


class TestResultDefaults:
    def test_text_cleaning_result_defaults(self) -> None:
        assert not TextCleaningResult().cleaned_text

    def test_entity_extraction_result_defaults(self) -> None:
        result = EntityExtractionResult()
        assert result.doc_type_hint is None
        assert result.signatories == []
        assert result.article_count is None

    def test_metadata_enrichment_result_defaults(self) -> None:
        result = MetadataEnrichmentResult()
        assert not result.source
        assert not result.language


class TestEnrichmentUpdate:
    def test_dump_excludes_none_fields(self) -> None:
        update = EnrichmentUpdate(cleaned_text="hello")
        dumped = {k: v for k, v in update if v is not None}
        assert dumped == {"cleaned_text": "hello"}


class TestEntityExtractionFailedError:
    def test_message(self) -> None:
        exc = EntityExtractionFailedError(reason="bad json")
        assert str(exc) == "Entity extraction failed: bad json"
        assert isinstance(exc, Exception)

    def test_raises_with_context(self) -> None:
        with pytest.raises(EntityExtractionFailedError, match="bad json"):
            raise EntityExtractionFailedError(reason="bad json")

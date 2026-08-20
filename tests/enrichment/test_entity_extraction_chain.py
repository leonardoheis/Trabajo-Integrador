import pytest

from classiflow.enrichment.prompts.entity_extraction import (
    EntityExtractionInput,
    build_entity_extraction_chain,
)
from classiflow.ingesta.llm_provider import MockLlm

_EXPECTED_YEAR = 1999
_EXPECTED_ARTICLE_COUNT = 3
_VALID_RESPONSE = (
    '{"doc_type_hint": "ordenanza", "number": "6801", "year": '
    f"{_EXPECTED_YEAR}, "
    '"issuing_body": "Concejo Municipal", "signatories": ["Hermes Binner"], '
    f'"article_count": {_EXPECTED_ARTICLE_COUNT}}}'
)
_MALFORMED_RESPONSE = "not json at all"


class TestBuildEntityExtractionChain:
    def test_parses_valid_response(self) -> None:
        chain = build_entity_extraction_chain(MockLlm(response=_VALID_RESPONSE))
        output = chain.invoke(EntityExtractionInput(cleaned_text="Artículo 1º ..."))
        assert output.doc_type_hint == "ordenanza"
        assert output.number == "6801"
        assert output.year == _EXPECTED_YEAR
        assert output.issuing_body == "Concejo Municipal"
        assert output.signatories == ["Hermes Binner"]
        assert output.article_count == _EXPECTED_ARTICLE_COUNT

    def test_raises_value_error_on_malformed_response(self) -> None:
        chain = build_entity_extraction_chain(MockLlm(response=_MALFORMED_RESPONSE))
        with pytest.raises(ValueError, match="No valid JSON object"):
            chain.invoke(EntityExtractionInput(cleaned_text="Artículo 1º ..."))

    def test_all_fields_optional_on_empty_object(self) -> None:
        chain = build_entity_extraction_chain(MockLlm(response="{}"))
        output = chain.invoke(EntityExtractionInput(cleaned_text="..."))
        assert output.doc_type_hint is None
        assert output.signatories == []

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


# The literal output that failed on decreto_837_2026.pdf: OCR noise put unescaped quotes
# inside a string value, which is malformed JSON rather than a regex-matching problem.
_UNESCAPED_QUOTES_RESPONSE = (
    '{"doc_type_hint": "decreto", "number": 3, "year": null, '
    '"issuing_body": "Municipalidad de Rosario", '
    '"signatories": ["LEDAD RODRIGUEZ", "110-""i""\',v-t,E ROSARIO Intendente"], '
    '"article_count": 3}'
)


class TestUnescapedQuotesInStringValues:
    def test_recovers_the_surrounding_fields(self) -> None:
        chain = build_entity_extraction_chain(MockLlm(response=_UNESCAPED_QUOTES_RESPONSE))
        output = chain.invoke(EntityExtractionInput(cleaned_text="..."))
        assert output.doc_type_hint == "decreto"
        assert output.issuing_body == "Municipalidad de Rosario"
        assert output.article_count == _EXPECTED_ARTICLE_COUNT

    def test_recovers_the_signatories_around_the_noise(self) -> None:
        chain = build_entity_extraction_chain(MockLlm(response=_UNESCAPED_QUOTES_RESPONSE))
        output = chain.invoke(EntityExtractionInput(cleaned_text="..."))
        assert output.signatories[0] == "LEDAD RODRIGUEZ"

    def test_leaves_a_valid_response_untouched(self) -> None:
        """The repair is a fallback: it must never rewrite output that already parsed."""
        chain = build_entity_extraction_chain(MockLlm(response=_VALID_RESPONSE))
        output = chain.invoke(EntityExtractionInput(cleaned_text="..."))
        assert output.signatories == ["Hermes Binner"]


class TestNumericActNumber:
    def test_coerces_an_integer_number_to_a_string(self) -> None:
        chain = build_entity_extraction_chain(MockLlm(response='{"number": 3}'))
        output = chain.invoke(EntityExtractionInput(cleaned_text="..."))
        assert output.number == "3"

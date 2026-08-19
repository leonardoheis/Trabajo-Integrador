import pytest

from classiflow.classification.prompts.primary_classification import (
    PrimaryClassificationInput,
    build_classification_chain,
)
from classiflow.ingesta.llm_provider import MockLlm

_VALID_RESPONSE = '{"label": "ordenanzas", "confidence": 0.91, "reasoning": "mentions ARTÍCULO"}'
_MALFORMED_RESPONSE = "not json at all"
_EXPECTED_CONFIDENCE = 0.91


class TestBuildClassificationChain:
    def test_parses_valid_response(self) -> None:
        chain = build_classification_chain(MockLlm(response=_VALID_RESPONSE))
        output = chain.invoke(PrimaryClassificationInput(cleaned_text="Artículo 1º ..."))
        assert output.label == "ordenanzas"
        assert output.confidence == _EXPECTED_CONFIDENCE
        assert output.all_scores == {"ordenanzas": 0.91}

    def test_raises_value_error_on_malformed_response(self) -> None:
        chain = build_classification_chain(MockLlm(response=_MALFORMED_RESPONSE))
        with pytest.raises(ValueError, match="No valid JSON object"):
            chain.invoke(PrimaryClassificationInput(cleaned_text="Artículo 1º ..."))

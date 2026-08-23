import pytest

from classiflow.classification.prompts.llm_judge import JudgeInput, build_judge_chain
from classiflow.ingesta.llm_provider import MockLlm

_VALID_RESPONSE = (
    '{"accept": true, "final_label": "ordenanzas", '
    '"reasoning": "label matches the document content"}'
)
_MALFORMED_RESPONSE = "not json at all"
_ACCEPT_WITH_LABEL_RESPONSE = (
    '{"accept": true, "final_label": "ordenanzas", '
    '"reasoning": "label matches the document content"}'
)


def _input(**overrides: object) -> JudgeInput:
    defaults: dict[str, object] = {
        "cleaned_text": "Artículo 1º — texto completo sin truncar ...",
        "primary_label": "ordenanzas",
        "primary_confidence": 0.6,
    }
    defaults.update(overrides)
    return JudgeInput.model_validate(defaults)


class TestBuildJudgeChain:
    def test_parses_valid_response(self) -> None:
        chain = build_judge_chain(MockLlm(response=_VALID_RESPONSE))
        output = chain.invoke(_input())
        assert output.accept is True
        assert output.reasoning == "label matches the document content"

    def test_raises_value_error_on_malformed_response(self) -> None:
        chain = build_judge_chain(MockLlm(response=_MALFORMED_RESPONSE))
        with pytest.raises(ValueError, match="No valid JSON object"):
            chain.invoke(_input())


class TestBuildJudgeChainFinalLabel:
    def test_parses_final_label_field(self) -> None:
        chain = build_judge_chain(MockLlm(response=_ACCEPT_WITH_LABEL_RESPONSE))
        output = chain.invoke(_input())
        assert output.final_label == "ordenanzas"

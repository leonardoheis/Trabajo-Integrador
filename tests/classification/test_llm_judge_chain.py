import pytest
from langchain_core.language_models import LLM

from classiflow.classification.bert.ood_scorer import OodMetrics
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


def _ood_metrics(**overrides: object) -> OodMetrics:
    defaults: dict[str, object] = {
        "mahalanobis_p_value": 0.484758,
        "mahalanobis_p_value_theoretical": 0.94,
        "cosine_z": -0.3552,
        "knn_distance": 12.4,
        "in_distribution": True,
        "mahalanobis_calibration_status": "refused_degenerate",
    }
    defaults.update(overrides)
    return OodMetrics.model_validate(defaults)


# Records the exact prompt build_judge_chain sends, so tests can assert on the
# rendered prompt content without importing the module's private _format_prompt.
class _PromptCapturingLlm(LLM):
    captured_prompt: str = ""

    def _call(self, prompt: str, stop: list[str] | None = None, **kwargs: object) -> str:
        del stop, kwargs
        self.captured_prompt = prompt
        return _ACCEPT_WITH_LABEL_RESPONSE

    @property
    def _llm_type(self) -> str:
        return "prompt-capturing-mock"


class TestFormatPromptOodSignals:
    def test_degenerate_mahalanobis_status_is_flagged_not_silently_trusted(self) -> None:
        llm = _PromptCapturingLlm()
        chain = build_judge_chain(llm)
        chain_input = _input(
            second_opinion_label="resoluciones",
            second_opinion_confidence=0.996,
            ood_metrics=_ood_metrics(),
            svm_agrees_with_prediction=False,
        )
        chain.invoke(chain_input)
        assert "degenerate calibration" in llm.captured_prompt
        assert "do not treat this value as trustworthy evidence" in llm.captured_prompt
        assert "0.484758" in llm.captured_prompt

    def test_in_distribution_and_svm_agreement_both_render(self) -> None:
        llm = _PromptCapturingLlm()
        chain = build_judge_chain(llm)
        chain_input = _input(
            second_opinion_label="resoluciones",
            second_opinion_confidence=0.996,
            ood_metrics=_ood_metrics(in_distribution=False),
            svm_agrees_with_prediction=False,
        )
        chain.invoke(chain_input)
        prompt = llm.captured_prompt
        assert "in_distribution: False" in prompt or "not in-distribution" in prompt.lower()
        assert "svm" in prompt.lower()

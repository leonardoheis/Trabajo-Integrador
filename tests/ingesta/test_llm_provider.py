from unittest.mock import MagicMock

import pytest

from classiflow.ingesta.exceptions import ModelLoadError, ModelNotFoundError
from classiflow.ingesta.llm_provider import MockLlm, get_llm, get_llm_langchain


class TestMockLlm:
    def test_invoke_returns_default_json_string(self) -> None:
        llm = MockLlm()
        result = llm.invoke("classify this document")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_custom_response_is_returned(self) -> None:
        payload = '{"decision": "reject", "confidence": 0.1}'
        llm = MockLlm(response=payload)
        assert llm.invoke("prompt") == payload

    def test_two_instances_are_independent(self) -> None:
        a = MockLlm(response="A")
        b = MockLlm(response="B")
        assert a.invoke("x") != b.invoke("x")


class TestGetLlm:
    def test_raises_model_load_error_when_model_path_is_invalid(self) -> None:
        get_llm.cache_clear()
        try:
            with pytest.raises(ModelLoadError):
                get_llm()  # LLM_MODEL_PATH="" → Llama raises → caught → ModelLoadError
        finally:
            get_llm.cache_clear()

    def test_raises_model_not_found_when_path_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("classiflow.settings.Settings.LLM_MODEL_PATH", "/no/such/model.gguf")
        mock_llama = MagicMock(side_effect=FileNotFoundError)
        monkeypatch.setattr("classiflow.ingesta.llm_provider.Llama", mock_llama)
        get_llm.cache_clear()
        try:
            with pytest.raises(ModelNotFoundError):
                get_llm()
        finally:
            get_llm.cache_clear()

    def test_is_lru_cached_with_maxsize_one(self) -> None:
        assert hasattr(get_llm, "cache_info")
        assert get_llm.cache_info().maxsize == 1

    def test_returns_same_instance_on_repeated_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = object()
        mock_llama = MagicMock(return_value=sentinel)
        monkeypatch.setattr("classiflow.ingesta.llm_provider.Llama", mock_llama)
        monkeypatch.setattr("classiflow.settings.Settings.LLM_MODEL_PATH", "fake/model.gguf")
        get_llm.cache_clear()
        try:
            first = get_llm()
            second = get_llm()
            assert first is second
            assert mock_llama.call_count == 1
        finally:
            get_llm.cache_clear()


class TestGetLlmLangchain:
    def test_is_lru_cached_with_maxsize_one(self) -> None:
        assert hasattr(get_llm_langchain, "cache_info")
        assert get_llm_langchain.cache_info().maxsize == 1

    def test_returns_same_instance_on_repeated_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = object()
        mock_llamacpp = MagicMock(return_value=sentinel)
        monkeypatch.setattr("classiflow.ingesta.llm_provider.LlamaCpp", mock_llamacpp)
        monkeypatch.setattr("classiflow.settings.Settings.LLM_MODEL_PATH", "fake/model.gguf")
        get_llm_langchain.cache_clear()
        try:
            first = get_llm_langchain()
            second = get_llm_langchain()
            assert first is second
            assert mock_llamacpp.call_count == 1
        finally:
            get_llm_langchain.cache_clear()

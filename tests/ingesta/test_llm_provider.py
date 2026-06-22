import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

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
    def test_raises_import_error_when_model_path_is_invalid(self) -> None:
        get_llm.cache_clear()
        try:
            with pytest.raises(ImportError, match="llama-cpp-python"):
                get_llm()  # LLM_MODEL_PATH="" → Llama raises ValueError → caught → ImportError
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
        fake_llms = ModuleType("langchain_community.llms")
        fake_llms.LlamaCpp = MagicMock(return_value=sentinel)  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "langchain_community.llms", fake_llms)
        monkeypatch.setattr("classiflow.settings.Settings.LLM_MODEL_PATH", "fake/model.gguf")
        get_llm_langchain.cache_clear()
        try:
            first = get_llm_langchain()
            second = get_llm_langchain()
            assert first is second
            assert fake_llms.LlamaCpp.call_count == 1  # type: ignore[attr-defined]
        finally:
            get_llm_langchain.cache_clear()

from unittest.mock import MagicMock

import pytest

from classiflow.ingesta.llm_provider import MockLlm, get_llm_langchain


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


_LRU_MAXSIZE = 4


class TestGetLlmLangchain:
    def test_is_lru_cached_with_maxsize_four(self) -> None:
        assert hasattr(get_llm_langchain, "cache_info")
        assert get_llm_langchain.cache_info().maxsize == _LRU_MAXSIZE

    def test_returns_same_instance_on_repeated_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = object()
        mock_llamacpp = MagicMock(return_value=sentinel)
        monkeypatch.setattr("classiflow.ingesta.llm_provider.LlamaCpp", mock_llamacpp)
        get_llm_langchain.cache_clear()
        try:
            first = get_llm_langchain("fake/model.gguf")
            second = get_llm_langchain("fake/model.gguf")
            assert first is second
            assert mock_llamacpp.call_count == 1
        finally:
            get_llm_langchain.cache_clear()

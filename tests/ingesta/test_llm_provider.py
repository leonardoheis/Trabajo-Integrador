from unittest.mock import MagicMock

import pytest

from classiflow.ingesta.llm_provider import (
    ChatTemplatedLlamaCpp,
    MockLlm,
    get_llm_langchain,
)


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
        monkeypatch.setattr("classiflow.ingesta.llm_provider.ChatTemplatedLlamaCpp", mock_llamacpp)
        get_llm_langchain.cache_clear()
        try:
            first = get_llm_langchain("fake/model.gguf")
            second = get_llm_langchain("fake/model.gguf")
            assert first is second
            assert mock_llamacpp.call_count == 1
        finally:
            get_llm_langchain.cache_clear()


def _fake_chat_client(template: str) -> MagicMock:
    client = MagicMock()
    client.metadata = {"tokenizer.chat_template": template}
    client.model = 0
    client.token_bos.return_value = 1
    client.token_eos.return_value = 2
    client.return_value = {"choices": [{"text": "ok"}]}
    return client


_EOS_TOKEN_ID = 2


def _make_chat_templated_llm(client: MagicMock) -> ChatTemplatedLlamaCpp:
    return ChatTemplatedLlamaCpp.model_construct(
        model_path="fake.gguf",
        client=client,
        stop=[],
        max_tokens=10,
        temperature=0.1,
        top_p=0.9,
        echo=False,
        repeat_penalty=1.1,
        top_k=40,
        logprobs=None,
        suffix=None,
        streaming=False,
    )


class TestChatTemplatedLlamaCpp:
    _TEMPLATE = (
        "{{ '<|user|>' + messages[0]['content'] + '<|end|>' }}"
        "{% if add_generation_prompt %}{{ '<|assistant|>' }}{% endif %}"
    )

    def test_invoke_wraps_prompt_in_model_chat_template(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _fake_chat_client(self._TEMPLATE)
        monkeypatch.setattr(
            "classiflow.ingesta.llm_provider.llama_cpp.llama_model_get_vocab",
            lambda model: model,
        )
        monkeypatch.setattr(
            "classiflow.ingesta.llm_provider.llama_cpp.llama_token_get_text",
            lambda _vocab, token_id: b"<|end|>" if token_id == _EOS_TOKEN_ID else b"<bos>",
        )
        llm = _make_chat_templated_llm(client)

        result = llm.invoke("hello prompt")

        assert result == "ok"
        sent_prompt = client.call_args.kwargs["prompt"]
        assert sent_prompt == "<|user|>hello prompt<|end|><|assistant|>"
        assert client.call_args.kwargs["stop"] == ["<|end|>"]

    def test_invoke_falls_back_to_raw_prompt_without_chat_template(self) -> None:
        client = _fake_chat_client(self._TEMPLATE)
        client.metadata = {}
        llm = _make_chat_templated_llm(client)

        result = llm.invoke("hello prompt")

        assert result == "ok"
        assert client.call_args.kwargs["prompt"] == "hello prompt"

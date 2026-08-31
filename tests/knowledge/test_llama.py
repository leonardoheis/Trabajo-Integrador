import asyncio
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from classiflow.knowledge.llm.exceptions import ChatLlmError
from classiflow.knowledge.llm.llama import LlamaCppChatLlm, get_chat_llm, unload_chat_llm


def _chunk(text: str) -> dict[str, object]:
    return {"choices": [{"delta": {"content": text}}]}


class TestLlamaCppChatLlmAstream:
    def test_yields_each_token_as_a_separate_chunk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_llm = MagicMock()
        fake_llm.create_chat_completion.return_value = iter([
            _chunk("Hello"),
            _chunk(" "),
            _chunk("world"),
        ])
        monkeypatch.setattr("classiflow.knowledge.llm.llama.get_chat_llm", lambda *_args: fake_llm)

        chat_llm = LlamaCppChatLlm(model_path="fake/model.gguf", n_ctx=8192, max_tokens=64)

        async def collect() -> list[str]:
            return [token async for token in chat_llm.astream("system", "user")]

        tokens = asyncio.run(collect())

        assert tokens == ["Hello", " ", "world"]
        fake_llm.create_chat_completion.assert_called_once()
        assert fake_llm.create_chat_completion.call_args.kwargs["stream"] is True

    def test_raises_chat_llm_error_when_the_stream_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_llm = MagicMock()

        CRASH_MESSAGE = "model crashed"

        def _broken_stream() -> Iterator[dict[str, object]]:
            yield _chunk("partial")
            raise RuntimeError(CRASH_MESSAGE)

        fake_llm.create_chat_completion.return_value = _broken_stream()
        monkeypatch.setattr("classiflow.knowledge.llm.llama.get_chat_llm", lambda *_args: fake_llm)

        chat_llm = LlamaCppChatLlm(model_path="fake/model.gguf", n_ctx=8192, max_tokens=64)

        async def collect() -> list[str]:
            return [token async for token in chat_llm.astream("system", "user")]

        with pytest.raises(ChatLlmError):
            asyncio.run(collect())


class TestUnloadChatLlm:
    def test_forces_a_reload_on_the_next_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        EXPECTED_CALL_COUNT_AFTER_FIRST_CALL = 1
        EXPECTED_CALL_COUNT_AFTER_RELOAD = 2
        mock_llama = MagicMock(side_effect=lambda **_kwargs: object())
        monkeypatch.setattr("classiflow.knowledge.llm.llama.Llama", mock_llama)
        get_chat_llm.cache_clear()
        try:
            get_chat_llm("fake/model.gguf", 8192)
            assert mock_llama.call_count == EXPECTED_CALL_COUNT_AFTER_FIRST_CALL

            unload_chat_llm()
            get_chat_llm("fake/model.gguf", 8192)

            assert mock_llama.call_count == EXPECTED_CALL_COUNT_AFTER_RELOAD
        finally:
            get_chat_llm.cache_clear()

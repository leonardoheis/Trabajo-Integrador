import asyncio
import time
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from classiflow.knowledge.llm.exceptions import ChatLlmError
from classiflow.knowledge.llm.llama import (
    LlamaCppChatLlm,
    generation_in_flight,
    get_chat_llm,
    is_chat_llm_busy,
    unload_chat_llm,
)


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


class TestGenerationLifecycle:
    """The in-flight counter must return to zero on every exit path.

    A counter that leaks blocks every later unload silently; one that under-counts lets a
    model be evicted mid-generation, which hangs llama.cpp.
    """

    def test_a_completed_stream_releases_the_counter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_llm = MagicMock()
        fake_llm.create_chat_completion.return_value = iter([_chunk("a"), _chunk("b")])
        monkeypatch.setattr("classiflow.knowledge.llm.llama.get_chat_llm", lambda *_args: fake_llm)
        chat_llm = LlamaCppChatLlm(model_path="fake/model.gguf", n_ctx=8192, max_tokens=64)

        async def collect() -> None:
            async for _token in chat_llm.astream("system", "user"):
                pass

        asyncio.run(collect())

        assert is_chat_llm_busy() is False

    def test_a_failed_stream_releases_the_counter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_llm = MagicMock()

        CRASH_MESSAGE = "model crashed"

        def _broken_stream() -> Iterator[dict[str, object]]:
            yield _chunk("partial")
            raise RuntimeError(CRASH_MESSAGE)

        fake_llm.create_chat_completion.return_value = _broken_stream()
        monkeypatch.setattr("classiflow.knowledge.llm.llama.get_chat_llm", lambda *_args: fake_llm)
        chat_llm = LlamaCppChatLlm(model_path="fake/model.gguf", n_ctx=8192, max_tokens=64)

        async def collect() -> None:
            async for _token in chat_llm.astream("system", "user"):
                pass

        with pytest.raises(ChatLlmError):
            asyncio.run(collect())

        assert is_chat_llm_busy() is False

    def test_a_long_generation_stops_when_the_consumer_leaves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # llama.cpp's loop cannot be interrupted from outside, so without a stop flag
        # checked between tokens an abandoned stream runs to completion holding the
        # counter -- which is what left it stuck at 1 in production.
        produced = 0

        def _endless_stream() -> Iterator[dict[str, object]]:
            nonlocal produced
            while True:
                produced += 1
                yield _chunk("x")

        fake_llm = MagicMock()
        fake_llm.create_chat_completion.return_value = _endless_stream()
        monkeypatch.setattr("classiflow.knowledge.llm.llama.get_chat_llm", lambda *_args: fake_llm)
        chat_llm = LlamaCppChatLlm(model_path="fake/model.gguf", n_ctx=8192, max_tokens=64)

        async def take_one_then_leave() -> None:
            stream = chat_llm.astream("system", "user")
            async for _token in stream:
                break
            await stream.aclose()

        asyncio.run(take_one_then_leave())

        assert is_chat_llm_busy() is False

    def test_an_abandoned_stream_releases_the_counter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The consumer walks away mid-generation, as a closed browser tab does. Without
        # closing the generator the counter stays held and every unload no-ops forever.
        fake_llm = MagicMock()
        fake_llm.create_chat_completion.return_value = iter(_chunk(str(i)) for i in range(1000))
        monkeypatch.setattr("classiflow.knowledge.llm.llama.get_chat_llm", lambda *_args: fake_llm)
        chat_llm = LlamaCppChatLlm(model_path="fake/model.gguf", n_ctx=8192, max_tokens=64)

        async def abandon_after_one_token() -> None:
            stream = chat_llm.astream("system", "user")
            async for _token in stream:
                break
            await stream.aclose()

        asyncio.run(abandon_after_one_token())

        assert is_chat_llm_busy() is False


class TestGenerationSerialization:
    def test_two_streams_never_run_at_the_same_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # llama.cpp corrupts its KV cache if two generations interleave on one handle,
        # surfacing as "IndexError: index N is out of bounds". Background summarization
        # overlapping a chat stream is how this happens in practice.
        concurrent = 0
        max_concurrent = 0

        def _tracked_stream() -> Iterator[dict[str, object]]:
            nonlocal concurrent, max_concurrent
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
            try:
                for _ in range(5):
                    time.sleep(0.01)
                    yield _chunk("x")
            finally:
                concurrent -= 1

        fake_llm = MagicMock()
        fake_llm.create_chat_completion.side_effect = lambda **_kwargs: _tracked_stream()
        monkeypatch.setattr("classiflow.knowledge.llm.llama.get_chat_llm", lambda *_args: fake_llm)
        chat_llm = LlamaCppChatLlm(model_path="fake/model.gguf", n_ctx=8192, max_tokens=64)

        async def drain() -> None:
            async for _token in chat_llm.astream("system", "user"):
                pass

        async def two_at_once() -> None:
            await asyncio.gather(drain(), drain())

        asyncio.run(two_at_once())

        assert max_concurrent == 1
        assert is_chat_llm_busy() is False


class TestUnloadChatLlm:
    def test_is_skipped_while_a_generation_is_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Evicting the handle mid-generation hangs llama.cpp; the guard must hold even
        # when the eviction request comes from an unrelated user's logout.
        mock_llama = MagicMock(side_effect=lambda **_kwargs: object())
        monkeypatch.setattr("classiflow.knowledge.llm.llama.Llama", mock_llama)
        get_chat_llm.cache_clear()
        try:
            get_chat_llm("fake/model.gguf", 8192)
            with generation_in_flight():
                unload_chat_llm()
                get_chat_llm("fake/model.gguf", 8192)
                assert mock_llama.call_count == 1  # still cached: no eviction happened
        finally:
            get_chat_llm.cache_clear()

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

import asyncio
import queue
import threading
from collections.abc import AsyncGenerator, Iterable, Iterator
from contextlib import AbstractContextManager
from functools import lru_cache

from llama_cpp import Llama
from loguru import logger

from classiflow.ingesta.exceptions import ModelLoadError, ModelNotFoundError
from classiflow.ingesta.llm_provider import n_gpu_layers
from classiflow.knowledge.llm.chat_llm import ChatLlm
from classiflow.knowledge.llm.exceptions import ChatLlmError
from classiflow.model_cache import evict_lru_cache
from classiflow.model_lifecycle import InFlightCounter
from classiflow.settings import Settings

_PROVIDER = "llama"


# Evicting the chat model while it is generating hangs llama.cpp -- observed as a
# pipeline job stuck forever at "processing" with zero steps recorded.
_active_generations = InFlightCounter("chat generation")

# llama.cpp's C bindings are not safe for concurrent use of one model handle: two
# generations interleaved on the same Llama object corrupt each other's KV cache and
# surface as IndexError deep inside llama_cpp. Every generation serializes on this.
_generation_lock = threading.Lock()


def generation_in_flight() -> AbstractContextManager[None]:
    """Hold the unload guard for the duration of one generation.

    Returns:
        A context manager that blocks chat-model eviction while held.
    """
    return _active_generations.in_flight()


def is_chat_llm_busy() -> bool:
    return _active_generations.is_busy()


@lru_cache(maxsize=2)
# Chat-sized GGUF handle, deliberately separate from ingesta.llm_provider's
# get_llm_langchain: that one is cached at n_ctx=2048 for the validation nodes and
# cleared by unload_slm() after every job. Retrieval passages plus a question do not
# fit in 2048, and the chat model should not be evicted by pipeline runs.
def get_chat_llm(model_path: str, n_ctx: int) -> Llama:
    try:
        return Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers(),
            seed=Settings.slm_seed,
            verbose=False,
        )
    except FileNotFoundError as exc:
        raise ModelNotFoundError(path=model_path) from exc
    except Exception as exc:
        raise ModelLoadError(path=model_path, cause=str(exc)) from exc


def evict_chat_llm_cache() -> None:
    """Drop the cached handle so gc can free the GGUF's CUDA context.

    Unguarded: callers must establish that no generation is in flight. GpuResidency does
    that under a lock it also holds across this call.
    """
    evict_lru_cache(get_chat_llm)


def unload_chat_llm() -> None:
    # Guarded convenience wrapper for callers that are not GpuResidency.
    if is_chat_llm_busy():
        logger.warning(
            "unload_chat_llm skipped: {} generation(s) in flight", _active_generations.count
        )
        return
    evict_chat_llm_cache()
    logger.info("unload_chat_llm: evicted")


class LlamaCppChatLlm(ChatLlm):
    """Local GGUF chat completion, for running the assistant fully offline."""

    def __init__(self, model_path: str = "", n_ctx: int = 0, max_tokens: int = 0) -> None:
        self._model_path = model_path or Settings.chat_model_path
        self._n_ctx = n_ctx or Settings.chat_model_n_ctx
        self._max_tokens = max_tokens or Settings.chat_max_tokens

    def _complete(self, system: str, user: str) -> str:
        llm = get_chat_llm(self._model_path, self._n_ctx)
        with _generation_lock, _active_generations.in_flight():
            try:
                response = llm.create_chat_completion(
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=self._max_tokens,
                    temperature=Settings.slm_temperature,
                    top_p=Settings.slm_top_p,
                )
            except Exception as exc:
                raise ChatLlmError(provider=_PROVIDER, cause=str(exc)) from exc
        return _first_message_content(response)

    @staticmethod
    def _tokens_until_stopped(stream: object, stop: threading.Event | None) -> Iterator[str]:
        # `stream=True` always yields an iterator, but create_chat_completion's return
        # type is a union with the non-streaming response, which mypy cannot narrow.
        if not isinstance(stream, Iterable):
            return
        # stop is checked between tokens: llama.cpp's loop cannot be interrupted from
        # outside, so an abandoned stream would otherwise generate to the end while
        # holding the in-flight counter.
        for chunk in stream:
            if stop is not None and stop.is_set():
                return
            token = _delta_content(chunk)
            if token:
                yield token

    def _stream_tokens(
        self, system: str, user: str, stop: threading.Event | None = None
    ) -> Iterator[str]:
        llm = get_chat_llm(self._model_path, self._n_ctx)
        # The lock spans the whole stream, not just its creation: llama.cpp advances its
        # KV cache on every token, so a second generation starting mid-stream corrupts
        # both. Background summarization overlapping a chat is the common case.
        with _generation_lock, _active_generations.in_flight():
            try:
                stream = llm.create_chat_completion(
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=self._max_tokens,
                    temperature=Settings.slm_temperature,
                    top_p=Settings.slm_top_p,
                    stream=True,
                )
                yield from self._tokens_until_stopped(stream, stop)
            except Exception as exc:
                raise ChatLlmError(provider=_PROVIDER, cause=str(exc)) from exc

    def _produce_tokens(
        self,
        system: str,
        user: str,
        token_queue: "queue.Queue[str | ChatLlmError | None]",
        stop: threading.Event,
    ) -> None:
        try:
            for token in self._stream_tokens(system, user, stop):
                token_queue.put(token)
        except ChatLlmError as exc:
            token_queue.put(exc)
        finally:
            token_queue.put(None)

    async def astream(self, system: str, user: str) -> AsyncGenerator[str, None]:
        # llama.cpp generation is blocking and CPU/GPU bound; running it inline would
        # freeze every other request (other jobs, health checks, open SSE streams) for
        # its whole duration. A background thread produces tokens from the blocking
        # stream=True generator and pushes them onto a thread-safe queue; this coroutine
        # drains that queue on the event loop, so each token reaches the caller as soon
        # as llama.cpp emits it instead of waiting for the whole completion.
        token_queue: queue.Queue[str | ChatLlmError | None] = queue.Queue()
        stop = threading.Event()
        thread = threading.Thread(
            target=self._produce_tokens, args=(system, user, token_queue, stop), daemon=True
        )
        thread.start()
        try:
            while (item := await asyncio.to_thread(token_queue.get)) is not None:
                if isinstance(item, ChatLlmError):
                    raise item
                yield item
        finally:
            # Set unconditionally: on a normal finish the producer has already exited, on
            # an early close this is what lets it stop instead of generating to the end.
            stop.set()
            # thread.join() is blocking; if the caller disconnects early (a dropped SSE
            # stream) this cleanup path must not freeze the event loop waiting for
            # llama.cpp's uninterruptible generation to finish on its own.
            await asyncio.to_thread(thread.join)


def _first_message_content(response: object) -> str:
    if not isinstance(response, dict):
        return ""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _delta_content(chunk: object) -> str:
    if not isinstance(chunk, dict):
        return ""
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    return content if isinstance(content, str) else ""

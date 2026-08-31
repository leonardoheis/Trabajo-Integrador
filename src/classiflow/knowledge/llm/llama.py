import asyncio
import queue
import threading
from collections.abc import AsyncIterator, Iterator
from functools import lru_cache

from llama_cpp import Llama

from classiflow.ingesta.exceptions import ModelLoadError, ModelNotFoundError
from classiflow.ingesta.llm_provider import n_gpu_layers
from classiflow.knowledge.llm.chat_llm import ChatLlm
from classiflow.knowledge.llm.exceptions import ChatLlmError
from classiflow.model_cache import evict_lru_cache
from classiflow.settings import Settings

_PROVIDER = "llama"


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


def unload_chat_llm() -> None:
    # Same reasoning as ingesta.llm_provider.unload_slm(): drop the lru_cache's reference
    # so gc can collect the Llama instance and its __del__ frees the GGUF's CUDA context.
    evict_lru_cache(get_chat_llm)


class LlamaCppChatLlm(ChatLlm):
    """Local GGUF chat completion, for running the assistant fully offline."""

    def __init__(self, model_path: str = "", n_ctx: int = 0, max_tokens: int = 0) -> None:
        self._model_path = model_path or Settings.chat_model_path
        self._n_ctx = n_ctx or Settings.chat_model_n_ctx
        self._max_tokens = max_tokens or Settings.chat_max_tokens

    def _complete(self, system: str, user: str) -> str:
        llm = get_chat_llm(self._model_path, self._n_ctx)
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

    def _stream_tokens(self, system: str, user: str) -> Iterator[str]:
        llm = get_chat_llm(self._model_path, self._n_ctx)
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
            for chunk in stream:
                token = _delta_content(chunk)
                if token:
                    yield token
        except Exception as exc:
            raise ChatLlmError(provider=_PROVIDER, cause=str(exc)) from exc

    def _produce_tokens(
        self, system: str, user: str, token_queue: "queue.Queue[str | ChatLlmError | None]"
    ) -> None:
        try:
            for token in self._stream_tokens(system, user):
                token_queue.put(token)
        except ChatLlmError as exc:
            token_queue.put(exc)
        finally:
            token_queue.put(None)

    async def astream(self, system: str, user: str) -> AsyncIterator[str]:
        # llama.cpp generation is blocking and CPU/GPU bound; running it inline would
        # freeze every other request (other jobs, health checks, open SSE streams) for
        # its whole duration. A background thread produces tokens from the blocking
        # stream=True generator and pushes them onto a thread-safe queue; this coroutine
        # drains that queue on the event loop, so each token reaches the caller as soon
        # as llama.cpp emits it instead of waiting for the whole completion.
        token_queue: queue.Queue[str | ChatLlmError | None] = queue.Queue()
        thread = threading.Thread(
            target=self._produce_tokens, args=(system, user, token_queue), daemon=True
        )
        thread.start()
        try:
            while (item := await asyncio.to_thread(token_queue.get)) is not None:
                if isinstance(item, ChatLlmError):
                    raise item
                yield item
        finally:
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

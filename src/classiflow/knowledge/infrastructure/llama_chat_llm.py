import asyncio
from collections.abc import AsyncIterator
from functools import lru_cache

from llama_cpp import Llama

from classiflow.ingesta.exceptions import ModelLoadError, ModelNotFoundError
from classiflow.ingesta.llm_provider import n_gpu_layers
from classiflow.knowledge.exceptions import ChatLlmError
from classiflow.settings import Settings

_PROVIDER = "llama"


@lru_cache(maxsize=2)
# Chat-sized GGUF handle, deliberately separate from ingesta.llm_provider.get_llm:
# that one is cached at n_ctx=2048 for the validation nodes and cleared by
# unload_slm() after every job. Retrieval passages plus a question do not fit in
# 2048, and the chat model should not be evicted by pipeline runs.
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


class LlamaCppChatLlm:
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

    async def astream(self, system: str, user: str) -> AsyncIterator[str]:
        # llama.cpp generation is blocking and CPU/GPU bound; running it inline would
        # freeze every other request (other jobs, health checks, open SSE streams) for
        # its whole duration. Yielded as a single chunk -- token-level streaming would
        # need a queue bridging the worker thread back to the event loop, which is not
        # worth it for the local fallback provider.
        yield await asyncio.to_thread(self._complete, system, user)


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

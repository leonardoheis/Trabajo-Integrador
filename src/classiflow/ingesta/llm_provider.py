import gc
from functools import lru_cache

import llama_cpp
import torch
from langchain_community.llms import LlamaCpp
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models import BaseLLM
from langchain_core.outputs import Generation, LLMResult
from llama_cpp import Llama
from pydantic import Field

from classiflow.ingesta.exceptions import ModelLoadError, ModelNotFoundError
from classiflow.settings import Settings


def n_gpu_layers() -> int:
    # -1 offloads all layers to GPU. llama_supports_gpu_offload() only reflects whether
    # this build has a GPU backend compiled in, not whether one is actually present, so
    # it's paired with a live torch.cuda.is_available() check before trusting it.
    if torch.cuda.is_available() and llama_cpp.llama_supports_gpu_offload():
        return -1
    return 0


class MockLlm(BaseLLM):
    response: str = Field(default='{"decision": "accept", "confidence": 0.95}')

    def _generate(  # type: ignore[override]  # BaseLLM declares **kwargs: Any; omitting it here is intentional
        self,
        prompts: list[str],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
    ) -> LLMResult:
        text = self.response
        if stop:
            for token in stop:
                if token in text:
                    text = text[: text.index(token)]
        if run_manager:
            run_manager.on_llm_new_token(text)
        return LLMResult(generations=[[Generation(text=text)] for _ in prompts])

    @property
    def _llm_type(self) -> str:
        return "mock"


@lru_cache(maxsize=4)
def get_llm(model_path: str) -> Llama:
    try:
        return Llama(
            model_path=model_path,
            n_ctx=2048,
            n_gpu_layers=n_gpu_layers(),
            seed=Settings.slm_seed,
            verbose=False,
        )
    except FileNotFoundError as exc:
        raise ModelNotFoundError(path=model_path) from exc
    except Exception as exc:
        raise ModelLoadError(path=model_path, cause=str(exc)) from exc


def unload_slm() -> None:
    # Drops the lru_cache's reference to the loaded Llama/LlamaCpp instances so gc can
    # collect them -- their __del__ frees the GGUF's CUDA context directly (ctypes-owned
    # memory, not PyTorch's caching allocator), releasing VRAM back to the driver.
    # ponytail: runs synchronously on the event loop (called once per finished job, not
    # a hot path) -- move to asyncio.to_thread if it ever shows up as request latency.
    get_llm.cache_clear()
    get_llm_langchain.cache_clear()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


@lru_cache(maxsize=4)
def get_llm_langchain(model_path: str) -> BaseLLM:
    try:
        return LlamaCpp(  # type: ignore[no-any-return]
            model_path=model_path,
            n_ctx=2048,
            n_gpu_layers=n_gpu_layers(),
            temperature=Settings.slm_temperature,
            top_p=Settings.slm_top_p,
            seed=Settings.slm_seed,
            verbose=False,
        )
    except FileNotFoundError as exc:
        raise ModelNotFoundError(path=model_path) from exc
    except Exception as exc:
        raise ModelLoadError(path=model_path, cause=str(exc)) from exc

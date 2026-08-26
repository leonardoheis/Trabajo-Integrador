import gc
from functools import lru_cache
from uuid import UUID

import llama_cpp
import torch
import weave
from langchain_community.llms.llamacpp import LlamaCpp
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models import BaseLLM
from langchain_core.outputs import Generation, LLMResult
from langchain_core.tracers.schemas import Run
from llama_cpp.llama_chat_format import Jinja2ChatFormatter
from pydantic import Field
from typing_extensions import override
from weave.integrations.langchain import WeaveTracer

from classiflow.ingesta.exceptions import ModelLoadError, ModelNotFoundError
from classiflow.settings import Settings


def _n_gpu_layers() -> int:
    # -1 offloads all layers to GPU. llama_supports_gpu_offload() only reflects whether
    # this build has a GPU backend compiled in, not whether one is actually present, so
    # it's paired with a live torch.cuda.is_available() check before trusting it.
    if torch.cuda.is_available() and llama_cpp.llama_supports_gpu_offload():
        return -1
    return 0


def _token_text(model: llama_cpp.Llama, token_id: int) -> str:
    vocab = llama_cpp.llama_model_get_vocab(model.model)
    text: bytes = llama_cpp.llama_token_get_text(vocab, token_id)
    return text.decode("utf-8", errors="replace")


class ChatTemplatedLlamaCpp(LlamaCpp):
    # Every model this app loads (Phi-4-mini, Gemma 4, ...) is instruction-tuned and
    # trained expecting its own chat-formatted prompt (e.g. Phi-4:
    # "<|user|>{content}<|end|><|assistant|>"). LlamaCpp's _call() sends the bare
    # prompt straight to llama.cpp's raw completion API with no role markers at all --
    # confirmed empirically that this makes an instruction-tuned model drift into
    # unstructured hallucinated continuation instead of following the instruction.
    # The fix reads each model's own chat_template out of its GGUF metadata (rather
    # than hardcoding per-model template strings) so it's correct for any model file
    # dropped into models/, including the eos token used to stop generation at the
    # template's own turn boundary.

    def _call(
        self,
        prompt: str,
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: str,
    ) -> str:
        model = self.client
        template = model.metadata.get("tokenizer.chat_template")
        if template is None:
            return super()._call(prompt, stop=stop, run_manager=run_manager, **kwargs)

        eos = _token_text(model, model.token_eos())
        # bos_token="" (not the model's real BOS text): llama_cpp's own tokenizer
        # already prepends BOS by default (Llama.tokenize(add_bos=True)), so a
        # template that also renders its bos_token (e.g. Gemma's "{{ bos_token }}")
        # would duplicate it -- confirmed via a "duplicate leading <bos>" runtime
        # warning otherwise. The tokenizer's own BOS insertion is kept as the single
        # source; only the template's role-tag structure is needed here.
        formatter = Jinja2ChatFormatter(
            template=template, bos_token="", eos_token=eos, add_generation_prompt=True
        )
        rendered = formatter(messages=[{"role": "user", "content": prompt}])
        rendered_stop = (
            [rendered.stop] if isinstance(rendered.stop, str) else list(rendered.stop or [])
        )
        combined_stop = list({*rendered_stop, *(stop or [])})
        return super()._call(rendered.prompt, stop=combined_stop, run_manager=run_manager, **kwargs)


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


def unload_slm() -> None:
    # Drops the lru_cache's reference to the loaded LlamaCpp instance so gc can
    # collect it -- its __del__ frees the GGUF's CUDA context directly (ctypes-owned
    # memory, not PyTorch's caching allocator), releasing VRAM back to the driver.
    # Only actually frees anything if nothing else still references the model, which is
    # why api/dependencies.py builds the *_chain nodes lazily rather than injecting
    # container-held chains.
    # ponytail: runs synchronously on the event loop (called once per finished job, not
    # a hot path) -- move to asyncio.to_thread if it ever shows up as request latency.
    get_llm_langchain.cache_clear()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


class PatchedWeaveTracer(WeaveTracer):
    # weave 0.53.6's usage extraction does generation.get("generation_info", {}).get(...)
    # and output.get("extra", {}).get(...), which raise when langchain sets those fields
    # to an explicit None (llama.cpp never populates them) -- the default only covers a
    # missing key. It runs inside _finish_run after the call is popped but before
    # finish_call, so a raise leaves the trace unfinished: no outputs, no token usage.
    # Filling in the empty dicts up front lets the call complete. Drop once weave
    # tolerates these Nones.
    @override
    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: object) -> Run:
        for batch in response.generations:
            for generation in batch:
                if generation.generation_info is None:
                    generation.generation_info = {}
        run = self.run_map.get(str(run_id))
        if run is not None and getattr(run, "extra", None) is None:
            run.extra = {}
        return super().on_llm_end(response, run_id=run_id, **kwargs)


def wandb_callbacks() -> list[BaseCallbackHandler]:
    # No key -> no tracer and no weave.init(), so tests and key-less clones never hit
    # the network. weave.init() is idempotent, so calling it per resolution is fine.
    if not Settings.wandb_api_key:
        return []
    weave.init(Settings.wandb_project)
    return [PatchedWeaveTracer()]


@lru_cache(maxsize=4)
def get_llm_langchain(model_path: str) -> BaseLLM:
    # Callbacks are resolved here rather than taken as a parameter -- this function is
    # lru_cached on model_path alone, so a per-call callbacks argument would either be
    # silently ignored on cache hits or force a separate cache entry (and a separate
    # multi-GB GGUF load) per distinct callback list.
    try:
        return ChatTemplatedLlamaCpp(
            model_path=model_path,
            n_ctx=Settings.slm_n_ctx,
            n_gpu_layers=_n_gpu_layers(),
            max_tokens=Settings.slm_max_tokens,
            temperature=Settings.slm_temperature,
            top_p=Settings.slm_top_p,
            seed=Settings.slm_seed,
            callbacks=wandb_callbacks() or None,
            verbose=False,
        )
    except FileNotFoundError as exc:
        raise ModelNotFoundError(path=model_path) from exc
    except Exception as exc:
        raise ModelLoadError(path=model_path, cause=str(exc)) from exc

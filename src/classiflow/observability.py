import os
from collections.abc import Callable
from uuid import UUID

import wandb
import weave
from langchain_core.outputs import LLMResult
from langchain_core.tracers.schemas import Run
from weave.integrations.langchain import WeaveTracer

from classiflow.settings import Settings

_OnLlmEnd = Callable[..., Run]
_patched_tracers: set[type] = set()


def _patched_on_llm_end(original: _OnLlmEnd) -> _OnLlmEnd:
    # weave 0.53.6's usage extraction does generation.get("generation_info", {}).get(...)
    # and output.get("extra", {}).get(...), which raise when langchain sets those fields
    # to an explicit None (llama.cpp never populates them) -- the default only covers a
    # missing key. It runs inside _finish_run after the call is popped but before
    # finish_call, so a raise leaves the trace unfinished: no outputs, no token usage.
    # Filling in the empty dicts up front lets the call complete.
    def on_llm_end(
        self: WeaveTracer, response: LLMResult, *, run_id: UUID, **kwargs: object
    ) -> Run:
        for batch in response.generations:
            for generation in batch:
                if generation.generation_info is None:
                    generation.generation_info = {}
        run = self.run_map.get(str(run_id))
        if run is not None and getattr(run, "extra", None) is None:
            run.extra = {}
        return original(self, response, run_id=run_id, **kwargs)

    return on_llm_end


def _patch_weave_tracer() -> None:
    # Patches the CLASS rather than passing a subclass as a callback. weave registers
    # WeaveTracer itself via langchain's register_configure_hook, which instantiates it
    # per run to trace EVERY runnable -- chains and LangGraph nodes included, not just
    # direct LLM calls. Substituting our own instance on the LLM object would trace only
    # that one object and lose the pipeline spans, so the fix has to land on the class
    # weave actually registers. Idempotent: re-patching a patched class is skipped.
    if WeaveTracer in _patched_tracers:
        return
    WeaveTracer.on_llm_end = _patched_on_llm_end(WeaveTracer.on_llm_end)  # type: ignore[method-assign]
    _patched_tracers.add(WeaveTracer)


def init_tracing() -> None:
    # Called once at app startup. Disabled -> weave.init() never runs and no network
    # request is made, so tests and clones without a key behave exactly as before.
    if not Settings.tracing_enabled:
        return
    # wandb's default console mode wraps sys.stdout/stderr to mirror them into the W&B
    # UI. On Windows that wrapper's flush() raises OSError: [WinError 1] (seen from
    # tqdm progress bars during model loading, and from uvicorn's own access logger),
    # which crashes any request that loads a HuggingFace/tqdm-using model mid-trace.
    # "off" disables only the console capture -- metric/trace logging is unaffected.
    wandb.setup(settings=wandb.Settings(console="off"))
    _patch_weave_tracer()
    # weave reads WEAVE_TRACE_LANGCHAIN from os.environ during init() to decide whether
    # to register its global tracer. pydantic-settings loads .env into the Settings
    # model only, never into os.environ, so exporting it here is what carries a .env
    # value across. Defaults to "true": the global tracer is what gives full pipeline
    # coverage, and _patch_weave_tracer() above makes it safe.
    os.environ["WEAVE_TRACE_LANGCHAIN"] = Settings.WEAVE_TRACE_LANGCHAIN
    weave.init(Settings.WANDB_PROJECT)

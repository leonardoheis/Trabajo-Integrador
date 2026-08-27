import os
from uuid import UUID

import weave
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.tracers.schemas import Run
from typing_extensions import override
from weave.integrations.langchain import WeaveTracer

from classiflow.settings import Settings


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


def init_tracing() -> None:
    # Called once at app startup. Disabled -> weave.init() never runs and no network
    # request is made, so tests and clones without a key behave exactly as before.
    if not Settings.tracing_enabled:
        return
    # Not redundant despite the matching names: pydantic-settings loads .env into the
    # Settings model only, never into os.environ, and weave reads os.environ directly
    # during init() to decide whether to register its own global tracer. Exporting it
    # here is what carries a .env value across to weave. See the setting's own comment
    # for why it defaults to "false".
    os.environ["WEAVE_TRACE_LANGCHAIN"] = Settings.WEAVE_TRACE_LANGCHAIN
    weave.init(Settings.WANDB_PROJECT)


def tracing_callbacks() -> list[BaseCallbackHandler]:
    # Attached to each LLM as it is built; init_tracing() must have run first.
    if not Settings.tracing_enabled:
        return []
    return [PatchedWeaveTracer()]

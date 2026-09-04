"""Owns which models are resident on the GPU, and when it is safe to evict them.

Callers state intent -- what they are about to run -- rather than naming models. Which
models exist, which belong to the pipeline, and which are currently in use are
implementation details of this module.
"""

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from loguru import logger


class ModelRole(Enum):
    """What a model is for, which decides when it may be evicted."""

    CHAT = "chat"
    PIPELINE = "pipeline"


@dataclass(frozen=True)
class ManagedModel:
    """A model whose GPU residency this module controls.

    `is_busy` guards eviction. A model without one is only ever evicted when the verb
    itself has established that its owner is idle.
    """

    name: str
    role: ModelRole
    evict: Callable[[], None]
    is_busy: Callable[[], bool] | None = None
    # Serializes the guard check with the eviction. Without one, a check that passes and
    # then releases leaves a window for work to start before the model is freed.
    lock: threading.Lock = field(default_factory=threading.Lock)


class GpuResidency:
    def __init__(
        self,
        models: list[ManagedModel],
        pipeline_is_busy: Callable[[], bool],
    ) -> None:
        self._models = models
        self._pipeline_is_busy = pipeline_is_busy

    async def reserve_for_chat(self) -> None:
        """Free VRAM for the chat model by evicting the pipeline's."""
        if self._pipeline_is_busy():
            logger.info("reserve_for_chat skipped: a pipeline job is running")
            return
        await self._evict(role=ModelRole.PIPELINE)

    async def reserve_for_pipeline(self) -> None:
        """Free VRAM for the pipeline by evicting the chat model."""
        await self._evict(role=ModelRole.CHAT)

    async def reserve_for_judge(self) -> None:
        """Free the SLM so the judge's larger GGUF can load in its place.

        Narrower than reserve_for_pipeline: this runs *inside* a job, where the other
        pipeline models are still needed.
        """
        await self._evict(names={"slm"})

    async def release_all(self) -> None:
        """Evict everything not currently in use."""
        await self._evict(role=ModelRole.CHAT)
        if self._pipeline_is_busy():
            logger.info("release_all: pipeline models kept, a job is running")
            return
        await self._evict(role=ModelRole.PIPELINE)

    async def release_for_owner(self) -> None:
        """Evict everything on behalf of the caller that owns these models.

        Skips the is-the-owner-busy checks the other verbs apply: a pipeline job clears
        VRAM at its start and finish precisely because it is the thing about to use it,
        so refusing while that job runs would starve it. Per-model guards still hold --
        freeing a model mid-generation hangs llama.cpp whoever asks.
        """
        await self._evict()

    async def _evict(self, *, role: ModelRole | None = None, names: set[str] | None = None) -> None:
        for model in self._models:
            if role is not None and model.role is not role:
                continue
            if names is not None and model.name not in names:
                continue
            await asyncio.to_thread(_evict_if_idle, model)


def _evict_if_idle(model: ManagedModel) -> None:
    """Evict one model, holding its lock across both the guard check and the eviction."""
    with model.lock:
        if model.is_busy is not None and model.is_busy():
            logger.warning("{} not evicted: still in use", model.name)
            return
        model.evict()
        logger.info("{} evicted", model.name)


def build_default_residency() -> GpuResidency:
    """The five models this process manages, wired to their real caches.

    Imports are function-local because llm_judge imports this module: at module scope
    they would form an import cycle.

    Returns:
        A GpuResidency over the process's real model caches.
    """
    from classiflow.classification.nodes.second_opinion import unload_bert
    from classiflow.ingesta.llm_provider import unload_slm
    from classiflow.ingesta.nodes.node4_duplicate_control import (
        unload_duplicate_control_embedder,
    )
    from classiflow.knowledge.embeddings.embedder import unload_kb_embedder
    from classiflow.knowledge.llm.llama import evict_chat_llm_cache, is_chat_llm_busy
    from classiflow.services.pipeline.service import is_pipeline_busy

    return GpuResidency(
        [
            ManagedModel(
                # The raw cache clear, not unload_chat_llm(): the guard belongs to the
                # registry, which holds one lock across check and evict. unload_chat_llm
                # checks outside that lock, which is the race this module closes.
                name="chat LLM",
                role=ModelRole.CHAT,
                evict=evict_chat_llm_cache,
                is_busy=is_chat_llm_busy,
            ),
            ManagedModel(name="slm", role=ModelRole.PIPELINE, evict=unload_slm),
            ManagedModel(name="BETO", role=ModelRole.PIPELINE, evict=unload_bert),
            ManagedModel(name="KB embedder", role=ModelRole.PIPELINE, evict=unload_kb_embedder),
            ManagedModel(
                name="duplicate-control embedder",
                role=ModelRole.PIPELINE,
                evict=unload_duplicate_control_embedder,
            ),
        ],
        pipeline_is_busy=is_pipeline_busy,
    )

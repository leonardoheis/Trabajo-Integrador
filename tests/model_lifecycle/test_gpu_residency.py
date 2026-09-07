import threading

from classiflow.model_lifecycle.counter import InFlightCounter
from classiflow.model_lifecycle.residency import GpuResidency, ManagedModel, ModelRole

_MAIN_THREAD = threading.get_ident()


class _FakeCache:
    """Stands in for an lru_cache-backed model loader."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.evictions = 0
        self.evicted_on_thread: int | None = None

    def evict(self) -> None:
        self.evictions += 1
        self.evicted_on_thread = threading.get_ident()


def _residency(
    *,
    chat_busy: InFlightCounter | None = None,
    pipeline_busy: InFlightCounter | None = None,
) -> tuple[GpuResidency, dict[str, _FakeCache]]:
    caches = {
        "chat": _FakeCache("chat"),
        "slm": _FakeCache("slm"),
        "bert": _FakeCache("bert"),
        "kb_embedder": _FakeCache("kb_embedder"),
        "dup_embedder": _FakeCache("dup_embedder"),
    }
    chat_counter = chat_busy or InFlightCounter("chat")
    pipeline_counter = pipeline_busy or InFlightCounter("pipeline")
    models = [
        ManagedModel(
            name="chat",
            role=ModelRole.CHAT,
            evict=caches["chat"].evict,
            is_busy=chat_counter.is_busy,
        ),
        ManagedModel(name="slm", role=ModelRole.PIPELINE, evict=caches["slm"].evict),
        ManagedModel(name="bert", role=ModelRole.PIPELINE, evict=caches["bert"].evict),
        ManagedModel(
            name="kb_embedder", role=ModelRole.PIPELINE, evict=caches["kb_embedder"].evict
        ),
        ManagedModel(
            name="dup_embedder", role=ModelRole.PIPELINE, evict=caches["dup_embedder"].evict
        ),
    ]
    return GpuResidency(models, pipeline_is_busy=pipeline_counter.is_busy), caches


class TestReserveForChat:
    async def test_evicts_pipeline_models(self) -> None:
        residency, caches = _residency()

        await residency.reserve_for_chat()

        assert caches["slm"].evictions == 1
        assert caches["bert"].evictions == 1
        assert caches["chat"].evictions == 0

    async def test_does_not_evict_pipeline_models_during_a_job(self) -> None:
        pipeline = InFlightCounter("pipeline")
        residency, caches = _residency(pipeline_busy=pipeline)

        with pipeline.in_flight():
            await residency.reserve_for_chat()

        assert caches["slm"].evictions == 0
        assert caches["bert"].evictions == 0


class TestReserveForPipeline:
    async def test_evicts_the_chat_model(self) -> None:
        residency, caches = _residency()

        await residency.reserve_for_pipeline()

        assert caches["chat"].evictions == 1

    async def test_does_not_evict_the_chat_model_mid_generation(self) -> None:
        chat = InFlightCounter("chat")
        residency, caches = _residency(chat_busy=chat)

        with chat.in_flight():
            await residency.reserve_for_pipeline()

        assert caches["chat"].evictions == 0


class TestReserveForJudge:
    async def test_evicts_only_the_slm(self) -> None:
        # The judge swaps the small pipeline models out for its own larger GGUF; the
        # embedders and BETO are not what it needs room for.
        residency, caches = _residency()

        await residency.reserve_for_judge()

        assert caches["slm"].evictions == 1
        assert caches["bert"].evictions == 0
        assert caches["chat"].evictions == 0


class TestReleaseAll:
    async def test_evicts_everything_when_idle(self) -> None:
        residency, caches = _residency()

        await residency.release_all()

        assert all(cache.evictions == 1 for cache in caches.values())

    async def test_spares_the_chat_model_during_a_generation(self) -> None:
        chat = InFlightCounter("chat")
        residency, caches = _residency(chat_busy=chat)

        with chat.in_flight():
            await residency.release_all()

        assert caches["chat"].evictions == 0
        assert caches["slm"].evictions == 1

    async def test_spares_pipeline_models_during_a_job(self) -> None:
        pipeline = InFlightCounter("pipeline")
        residency, caches = _residency(pipeline_busy=pipeline)

        with pipeline.in_flight():
            await residency.release_all()

        assert caches["slm"].evictions == 0
        assert caches["chat"].evictions == 1


class TestReleaseForOwner:
    """The caller owns these models and is clearing them for its own next use.

    Deliberately unguarded: a pipeline job evicts at start and finish precisely because
    it is the thing using them. A busy-check would refuse and starve the job of VRAM.
    """

    async def test_evicts_everything_regardless_of_guards(self) -> None:
        chat = InFlightCounter("chat")
        pipeline = InFlightCounter("pipeline")
        residency, caches = _residency(chat_busy=chat, pipeline_busy=pipeline)

        with pipeline.in_flight():
            await residency.release_for_owner()

        assert all(cache.evictions == 1 for cache in caches.values())

    async def test_still_spares_a_model_that_is_actively_generating(self) -> None:
        # The one guard that survives: freeing the chat model mid-generation hangs
        # llama.cpp, which no ownership claim makes safe.
        chat = InFlightCounter("chat")
        residency, caches = _residency(chat_busy=chat)

        with chat.in_flight():
            await residency.release_for_owner()

        assert caches["chat"].evictions == 0
        assert caches["slm"].evictions == 1


class TestEvictionRunsOffTheEventLoop:
    async def test_blocking_work_does_not_run_on_the_event_loop(self) -> None:
        # gc.collect() and torch.cuda.empty_cache() block; running them inline stalls
        # every other request for their duration.
        residency, caches = _residency()

        await residency.release_all()

        assert caches["chat"].evicted_on_thread != _MAIN_THREAD


class TestGuardRace:
    async def test_a_generation_starting_during_the_check_is_not_evicted(self) -> None:
        # The guard must cover check *and* evict as one atomic step. A check that
        # releases its lock before evicting leaves a window in which a generation can
        # begin -- and llama.cpp hangs if its model is freed mid-generation.
        model_lock = threading.Lock()
        lock_held_during_eviction: list[bool] = []

        def evict_recording_whether_the_lock_is_held() -> None:
            # A generation starting now would have to acquire this lock first. If it is
            # free while we evict, the model can be freed mid-generation.
            acquired = model_lock.acquire(blocking=False)
            lock_held_during_eviction.append(not acquired)
            if acquired:
                model_lock.release()

        residency = GpuResidency(
            [
                ManagedModel(
                    name="chat",
                    role=ModelRole.CHAT,
                    evict=evict_recording_whether_the_lock_is_held,
                    is_busy=lambda: False,
                    lock=model_lock,
                )
            ],
            pipeline_is_busy=lambda: False,
        )

        await residency.release_all()

        assert lock_held_during_eviction == [True]

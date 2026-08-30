import gc
from typing import Protocol, runtime_checkable

import torch


@runtime_checkable
class _CachedLoader(Protocol):
    def cache_clear(self) -> None: ...


def evict_lru_cache(cached_fn: _CachedLoader) -> None:
    # ponytail: runs synchronously on the event loop (called once per finished job --
    # now up to twice per job across 5 different model caches -- not a hot path) --
    # move to asyncio.to_thread if it ever shows up as request latency.
    cached_fn.cache_clear()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

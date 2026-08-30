import gc
from typing import Protocol, runtime_checkable

import torch


@runtime_checkable
class _CachedLoader(Protocol):
    def cache_clear(self) -> None: ...


def evict_lru_cache(cached_fn: _CachedLoader) -> None:
    cached_fn.cache_clear()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

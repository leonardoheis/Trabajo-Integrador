from functools import lru_cache

from classiflow.model_cache import evict_lru_cache


class TestEvictLruCache:
    def test_forces_a_reload_on_the_next_call(self) -> None:
        EXPECTED_CALL_COUNT_AFTER_FIRST_CALL = 1
        EXPECTED_CALL_COUNT_AFTER_RELOAD = 2
        calls = []

        @lru_cache(maxsize=1)
        def _load(key: str) -> object:
            calls.append(key)
            return object()

        _load("a")
        assert len(calls) == EXPECTED_CALL_COUNT_AFTER_FIRST_CALL

        evict_lru_cache(_load)
        _load("a")

        assert len(calls) == EXPECTED_CALL_COUNT_AFTER_RELOAD

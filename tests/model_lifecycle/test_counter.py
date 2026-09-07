import threading

import pytest
from loguru import logger

from classiflow.model_lifecycle.counter import InFlightCounter

_EXPECTED_CONCURRENT_INCREMENTS = 50


class TestInFlightCounter:
    def test_starts_idle(self) -> None:
        assert InFlightCounter("test").is_busy() is False

    def test_is_busy_while_held(self) -> None:
        counter = InFlightCounter("test")
        with counter.in_flight():
            assert counter.is_busy() is True
        assert counter.is_busy() is False

    def test_releases_when_the_body_raises(self) -> None:
        counter = InFlightCounter("test")
        with pytest.raises(RuntimeError), counter.in_flight():
            raise RuntimeError
        assert counter.is_busy() is False

    def test_stays_busy_until_the_last_holder_releases(self) -> None:
        counter = InFlightCounter("test")
        with counter.in_flight():
            with counter.in_flight():
                assert counter.is_busy() is True
            assert counter.is_busy() is True
        assert counter.is_busy() is False


class TestUnderflow:
    def test_a_double_release_is_logged_not_silently_clamped(self) -> None:
        # An underflow means a lifecycle path releases twice. Clamping without a signal
        # would let a model be evicted while still in use.
        messages: list[str] = []
        sink_id = logger.add(messages.append, level="ERROR")
        try:
            counter = InFlightCounter("test")
            with counter.in_flight():
                pass
            counter.release()
        finally:
            logger.remove(sink_id)

        assert counter.is_busy() is False
        assert counter.count == 0
        assert any("underflow" in message for message in messages)


class TestThreadSafety:
    def test_concurrent_increments_are_not_lost(self) -> None:
        # The chat counter is mutated from the background thread astream() spawns, not
        # only from the event loop.
        counter = InFlightCounter("test")
        barrier = threading.Barrier(_EXPECTED_CONCURRENT_INCREMENTS)

        def acquire_and_hold() -> None:
            barrier.wait()
            counter.acquire()

        threads = [
            threading.Thread(target=acquire_and_hold)
            for _ in range(_EXPECTED_CONCURRENT_INCREMENTS)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert counter.count == _EXPECTED_CONCURRENT_INCREMENTS

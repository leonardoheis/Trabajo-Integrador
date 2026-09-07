import contextlib
import threading
from collections.abc import Iterator

from loguru import logger


class InFlightCounter:
    """Counts work currently using a shared resource, so it is not torn down mid-use.

    Two instances exist: one for chat generations, one for pipeline jobs. Both guard
    model eviction -- freeing a model's VRAM while it is generating hangs llama.cpp.

    Thread-safe: the chat counter is mutated from the background thread `astream()`
    spawns, not only from the event loop.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._count = 0
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def is_busy(self) -> bool:
        with self._lock:
            return self._count > 0

    def acquire(self) -> None:
        with self._lock:
            self._count += 1

    def release(self) -> None:
        with self._lock:
            if self._count <= 0:
                # A lifecycle path released twice. Logged rather than silently clamped:
                # an under-count lets a model be evicted while still in use.
                logger.error(
                    "{} counter underflow -- released more times than acquired", self._name
                )
                self._count = 0
                return
            self._count -= 1

    @contextlib.contextmanager
    def in_flight(self) -> Iterator[None]:
        """Hold the guard for the duration of one unit of work."""
        self.acquire()
        try:
            yield
        finally:
            self.release()

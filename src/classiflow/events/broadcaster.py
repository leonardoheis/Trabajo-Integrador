import asyncio
from collections.abc import AsyncGenerator

from classiflow.domain.job import JobStatus, NodeEvent


class EventBroadcaster:
    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[NodeEvent | None]] = {}
        # Retained after queue deletion so late emits/subscribes are rejected without
        # accidentally recreating a queue for a job that has already finished.
        self._closed: set[str] = set()

    def _get_or_create(self, job_id: str) -> asyncio.Queue[NodeEvent | None]:
        if job_id not in self._queues:
            self._queues[job_id] = asyncio.Queue()
        return self._queues[job_id]

    async def emit(self, event: NodeEvent) -> None:
        if event.job_id in self._closed:
            return
        queue = self._get_or_create(event.job_id)
        await queue.put(event)

    async def subscribe(self, job_id: str) -> AsyncGenerator[NodeEvent, None]:
        if job_id in self._closed:
            return
        queue = self._get_or_create(job_id)
        while True:
            event = await queue.get()
            if event is None:  # sentinel — close signal
                break
            yield event
            if event.status == JobStatus.DONE:
                break

    def is_closed(self, job_id: str) -> bool:
        return job_id in self._closed

    async def close(self, job_id: str) -> None:
        if job_id in self._queues:
            await self._queues[job_id].put(None)  # sentinel
            del self._queues[job_id]
        self._closed.add(job_id)

import asyncio
from typing import TYPE_CHECKING, cast

from fastapi import BackgroundTasks

from classiflow.database.repositories.document_kb import InMemoryDocumentKbRepository
from classiflow.database.repositories.document_steps import InMemoryDocumentStepsRepository
from classiflow.database.repositories.enriched_record import InMemoryEnrichedRecordRepository
from classiflow.database.repositories.job import InMemoryJobRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.services.pipeline.service import PipelineService
from tests.fakes import make_indexer

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from classiflow.storage.document_storage import IDocumentStorage

_SEMAPHORE_CAP = 2
_JOB_COUNT = 5


class _ConcurrencyTrackingCoordinator:
    def __init__(self, sleep_seconds: float) -> None:
        self._sleep_seconds = sleep_seconds
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = asyncio.Lock()

    async def ainvoke(self, state: dict[str, object]) -> dict[str, object]:
        async with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(self._sleep_seconds)
        async with self._lock:
            self.in_flight -= 1
        return {
            "job_id": state["job_id"],
            "filename": state["filename"],
            "final_status": "rejected",
            "rejection_reason": "test",
        }


class TestPipelineServiceConcurrencyCap:
    async def test_semaphore_caps_concurrent_coordinator_runs(self) -> None:
        coordinator = _ConcurrencyTrackingCoordinator(sleep_seconds=0.05)
        service = PipelineService(
            job_repo=InMemoryJobRepository(),
            document_steps_repo=InMemoryDocumentStepsRepository(),
            enriched_record_repo=InMemoryEnrichedRecordRepository(),
            broadcaster=EventBroadcaster(),
            coordinator=cast("CompiledStateGraph", coordinator),
            enrichment_coordinator=cast(
                "CompiledStateGraph", None
            ),  # unused: final_status != accepted
            document_storage=cast("IDocumentStorage", None),  # unused: extraction key absent
            classification_coordinator=cast("CompiledStateGraph", None),  # unused: not accepted
            job_semaphore=asyncio.Semaphore(_SEMAPHORE_CAP),
            indexer=make_indexer(),  # unused: coordinator always rejects
            document_kb_repo=InMemoryDocumentKbRepository(),  # unused: coordinator always rejects
        )
        background_tasks = BackgroundTasks()
        for i in range(_JOB_COUNT):
            await service.start(background_tasks, f"doc-{i}.pdf", b"x")

        await asyncio.gather(*[task() for task in background_tasks.tasks])

        assert coordinator.max_in_flight <= _SEMAPHORE_CAP

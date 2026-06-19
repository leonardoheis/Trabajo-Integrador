import asyncio

import pytest

from classiflow.shared.domain.job import AgentEvent, JobStatus
from classiflow.shared.events.broadcaster import EventBroadcaster

pytestmark = pytest.mark.anyio


async def test_emit_and_subscribe() -> None:
    broadcaster = EventBroadcaster()
    event = AgentEvent(job_id="job-1", agent="ingestion", status=JobStatus.PASSED)

    await broadcaster.emit(event)

    received: list[AgentEvent] = []
    async for evt in broadcaster.subscribe("job-1"):
        received.append(evt)
        break  # only one event; avoid blocking

    assert len(received) == 1
    assert received[0].job_id == "job-1"
    assert received[0].agent == "ingestion"
    assert received[0].status == JobStatus.PASSED


async def test_done_status_closes_stream() -> None:
    broadcaster = EventBroadcaster()
    event = AgentEvent(job_id="job-2", agent="router", status=JobStatus.DONE)

    await broadcaster.emit(event)

    received: list[AgentEvent] = []

    async def consume() -> None:
        received.extend([evt async for evt in broadcaster.subscribe("job-2")])

    await asyncio.wait_for(consume(), timeout=2.0)

    assert len(received) == 1
    assert received[0].status == JobStatus.DONE


async def test_close_sends_sentinel() -> None:
    # Start subscribing first (so the queue exists), then close — subscriber must exit cleanly.
    broadcaster = EventBroadcaster()
    job_id = "job-3"
    received: list[AgentEvent] = []

    async def consume() -> None:
        received.extend([evt async for evt in broadcaster.subscribe(job_id)])

    task = asyncio.create_task(consume())
    # Yield control so that consume() starts and is waiting on queue.get()
    await asyncio.sleep(0)
    await broadcaster.close(job_id)
    await asyncio.wait_for(task, timeout=2.0)

    assert received == []  # sentinel caused immediate exit, no events yielded


async def test_early_disconnect() -> None:
    broadcaster = EventBroadcaster()
    job_id = "job-4"

    # Emit several events
    for i in range(3):
        await broadcaster.emit(
            AgentEvent(job_id=job_id, agent=f"agent-{i}", status=JobStatus.STARTED)
        )

    # Close before consuming all events
    await broadcaster.close(job_id)

    assert broadcaster.is_closed(job_id)


async def test_subscribe_after_close_exits_immediately() -> None:
    broadcaster = EventBroadcaster()
    job_id = "job-5"

    await broadcaster.close(job_id)

    received: list[AgentEvent] = []

    async def consume() -> None:
        received.extend([evt async for evt in broadcaster.subscribe(job_id)])

    await asyncio.wait_for(consume(), timeout=2.0)

    assert received == []
    assert broadcaster.is_closed(job_id)


async def test_emit_after_close_is_noop() -> None:
    broadcaster = EventBroadcaster()
    job_id = "job-6"

    await broadcaster.close(job_id)
    await broadcaster.emit(AgentEvent(job_id=job_id, agent="agent", status=JobStatus.STARTED))

    # emit must not recreate the queue after close
    assert broadcaster.is_closed(job_id)

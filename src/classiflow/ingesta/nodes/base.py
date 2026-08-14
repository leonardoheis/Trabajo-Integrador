import time
from abc import abstractmethod

from classiflow.database.repositories.audit import AuditDetail
from classiflow.domain.job import JobStatus, NodeEvent
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.domain.context import JobContext
from classiflow.services.audit.service import AuditService


class BaseNode:
    # Subclasses: if run() does a blocking, CPU-bound call (SLM invocation, embedding
    # computation, OCR, ...), wrap it in `await asyncio.to_thread(...)`. run() is a
    # coroutine that the coordinator awaits directly on the event loop — unlike a plain
    # sync node function, which LangGraph itself auto-dispatches to a thread — so a bare
    # blocking call here freezes every other concurrent request (other jobs, health
    # checks, open SSE streams) for its duration. See node2/node3's SLM calls and
    # node4's embedding calls for the pattern.
    def __init__(self, audit: AuditService, broadcaster: EventBroadcaster) -> None:
        self.audit = audit
        self.broadcaster = broadcaster

    @property
    @abstractmethod
    def name(self) -> str: ...

    async def _emit_started(self, ctx: JobContext) -> float:
        await self.broadcaster.emit(
            NodeEvent(job_id=ctx.job_id, node=self.name, status=JobStatus.STARTED)
        )
        return time.monotonic()

    async def _emit_and_audit(
        self,
        ctx: JobContext,
        start: float,
        *,
        passed: bool,
        detail: AuditDetail,
    ) -> None:
        duration_ms = int((time.monotonic() - start) * 1000)
        status = JobStatus.PASSED if passed else JobStatus.FAILED
        await self.broadcaster.emit(NodeEvent(job_id=ctx.job_id, node=self.name, status=status))
        await self.audit.record(
            ctx.job_id, self.name, status.value, duration_ms=duration_ms, detail=detail
        )

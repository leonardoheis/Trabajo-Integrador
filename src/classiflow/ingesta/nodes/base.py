import time
from abc import abstractmethod

from pydantic import BaseModel, ConfigDict

from classiflow.database.repositories.audit import AuditDetail
from classiflow.domain.job import JobStatus, NodeEvent
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.domain.context import JobContext
from classiflow.services.audit.service import AuditService


class BaseNode(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    audit: AuditService
    broadcaster: EventBroadcaster

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

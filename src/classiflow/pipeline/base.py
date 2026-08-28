import time
from abc import abstractmethod
from typing import ClassVar, Protocol

import weave

from classiflow.database.repositories.audit import AuditDetail
from classiflow.domain.job import JobStatus, NodeEvent
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService


class _CallWithSelfInput(Protocol):
    # weave.op's call_display_name callable receives its own weave.trace.weave_client
    # .Call type, which isn't part of weave's public API -- this Protocol names only
    # the one attribute this module actually reads instead of importing a private path.
    inputs: dict[str, object]


def _display_name(call: _CallWithSelfInput) -> str:
    node = call.inputs["self"]
    assert isinstance(node, BaseNode)
    return node.name


def _drop_self(inputs: dict[str, object]) -> dict[str, object]:
    # `self` holds injected services (AuditService, EventBroadcaster, DB repos, ...)
    # that aren't meaningful trace data and aren't guaranteed JSON-serializable --
    # only the node's own call arguments (already the same data every node passes to
    # AuditDetail.model_validate for its audit record) are worth logging to weave.
    return {k: v for k, v in inputs.items() if k != "self"}


class BaseNode:
    # Wraps every subclass's run() in weave.op() at class-definition time -- one seam
    # for all ~15 pipeline nodes instead of decorating each run() by hand, and new
    # nodes get tracing for free. weave.op() is a no-op (one warning, zero network/GPU
    # cost) when tracing is disabled (classiflow.observability.init_tracing() never
    # called weave.init(), e.g. tests and clones without a WANDB_API_KEY).
    _weave_traced: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        run = cls.__dict__.get("run")
        if run is not None and not cls.__dict__.get("_weave_traced", False):
            cls.run = weave.op(  # type: ignore[attr-defined]
                run,
                call_display_name=_display_name,
                postprocess_inputs=_drop_self,
            )
            cls._weave_traced = True

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

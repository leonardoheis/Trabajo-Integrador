from typing import Protocol

from classiflow.database.models import Job


class UnsetType:
    def __repr__(self) -> str:
        return "UNSET"


# Distinguishes "caller didn't touch this field" (leave it as-is) from "caller passed
# None" (clear it) — a plain `None` default can't express that difference, and every
# update_status() call would otherwise silently wipe fields it never meant to touch.
# UnsetType appears in update_status()'s public signature below, so — unlike a normal
# implementation detail — it can't be underscore-prefixed; only UNSET itself is meant
# to ever be constructed, but the type has to be importable by anything that calls or
# implements this Protocol.
UNSET = UnsetType()


class IJobRepository(Protocol):
    async def create(self, job: Job) -> None: ...
    async def find_by_job_id(self, job_id: str) -> Job | None: ...

    # Each kwarg below is an independently-optional UNSET-sentinel field (see UnsetType
    # above); collapsing them into one param object would lose the per-field opt-in
    # this pattern exists for.
    async def update_status(
        self,
        job_id: str,
        status: str,
        *,
        rejection_reason: str | UnsetType | None = UNSET,
        failed_at_node: str | UnsetType | None = UNSET,
        review_action_needed: str | UnsetType | None = UNSET,
        extracted_text: str | UnsetType | None = UNSET,
    ) -> None: ...
    async def list_all(self) -> list[Job]: ...

    # PipelineService._run() is a FastAPI BackgroundTask that keeps writing long after
    # its originating request has returned. Every write repo in this codebase only
    # flush()es and relies on get_session's teardown to commit() once, atomically, at
    # request end -- correct for normal short-lived requests, but that teardown fires
    # once the background task itself finishes, so nothing _run() writes (Job.status,
    # audit records, document steps -- all sharing this same session) is visible to any
    # other request's session until the whole multi-minute pipeline is already done.
    # Only PipelineService calls this, at each state transition, to make its own
    # long-running writes durable and visible incrementally instead of all-at-once.
    async def commit(self) -> None: ...

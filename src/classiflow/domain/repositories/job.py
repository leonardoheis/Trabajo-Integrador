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
    async def update_status(
        self,
        job_id: str,
        status: str,
        *,
        rejection_reason: str | UnsetType | None = UNSET,
        failed_at_node: str | UnsetType | None = UNSET,
        review_action_needed: str | UnsetType | None = UNSET,
    ) -> None: ...
    async def list_all(self) -> list[Job]: ...

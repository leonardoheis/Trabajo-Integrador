from typing import Protocol

from classiflow.shared.database.models import HumanDecision


class IHumanDecisionRepository(Protocol):
    async def save(self, decision: HumanDecision) -> None: ...
    async def decisions_for_job(self, job_id: str) -> list[HumanDecision]: ...

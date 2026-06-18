from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from sqlalchemy import select

from classiflow.shared.database.models import HumanDecision

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class IHumanDecisionRepository(Protocol):
    async def save(self, decision: HumanDecision) -> None: ...
    async def decisions_for_job(self, job_id: str) -> list[HumanDecision]: ...


class SqlHumanDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, decision: HumanDecision) -> None:
        self._session.add(decision)
        await self._session.flush()

    async def decisions_for_job(self, job_id: str) -> list[HumanDecision]:
        result = await self._session.execute(
            select(HumanDecision)
            .where(HumanDecision.job_id == job_id)
            .order_by(HumanDecision.decided_at)
        )
        return list(result.scalars().all())


class InMemoryHumanDecisionRepository:
    def __init__(self) -> None:
        self._decisions: list[HumanDecision] = []

    async def save(self, decision: HumanDecision) -> None:
        self._decisions.append(decision)

    async def decisions_for_job(self, job_id: str) -> list[HumanDecision]:
        return [d for d in self._decisions if d.job_id == job_id]

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from classiflow.shared.database.models import HashRecord


class SqlHashRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, sha256: str) -> bool:
        result = await self._session.execute(select(HashRecord).where(HashRecord.sha256 == sha256))
        return result.scalar_one_or_none() is not None

    async def save(self, sha256: str, job_id: str) -> None:
        self._session.add(HashRecord(sha256=sha256, job_id=job_id))
        await self._session.flush()


class InMemoryHashRepository:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def exists(self, sha256: str) -> bool:
        return sha256 in self._store

    async def save(self, sha256: str, job_id: str) -> None:
        self._store[sha256] = job_id

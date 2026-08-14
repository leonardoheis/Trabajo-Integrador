"""get_session() commit/rollback behavior — driven manually like FastAPI drives it."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from classiflow.database import base as database_base
from classiflow.database.base import Base, get_session
from classiflow.database.models import AllowedUser

pytestmark = pytest.mark.anyio


@pytest.fixture
async def sessionmaker(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    # A real file (not sqlite:///:memory:) so two independent sessions/connections
    # genuinely share one database — proving commit persisted, not just flushed
    # within a single session's own view of its own pending changes.
    db_path = f"{tmp_path}/test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    # get_session() reads from this cached factory — point it at our throwaway db
    # instead of fighting the module's @lru_cache with cache_clear() calls.
    monkeypatch.setattr(database_base, "_get_session_factory", lambda: factory)
    yield factory
    await engine.dispose()


async def _count_allowed_users(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    async with sessionmaker() as verify_session:
        result = await verify_session.execute(select(AllowedUser))
        return len(result.scalars().all())


async def test_get_session_commits_on_success(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async for session in get_session():
        session.add(AllowedUser(email="committed@test.com"))

    assert await _count_allowed_users(sessionmaker) == 1


async def test_get_session_rolls_back_on_error(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    agen = get_session()
    session = await anext(agen)
    session.add(AllowedUser(email="never-committed@test.com"))
    await session.flush()  # visible inside this transaction, same as a real repo.save()

    # Mirrors what FastAPI does when a route handler raises: it throws the error
    # back into the paused generator, instead of just abandoning it.
    with pytest.raises(ValueError, match="boom"):
        await agen.athrow(ValueError, ValueError("boom"))

    assert await _count_allowed_users(sessionmaker) == 0

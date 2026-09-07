from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy import event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import ConnectionPoolEntry

from classiflow.settings import Settings


class Base(DeclarativeBase):
    pass


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _tune_sqlite_connection(
    dbapi_connection: DBAPIConnection, _record: ConnectionPoolEntry
) -> None:
    cursor = dbapi_connection.cursor()
    try:
        # busy_timeout first: switching journal mode itself needs an exclusive lock, so
        # without it this very pragma raises "database is locked" under the concurrency
        # WAL exists to relieve. connect_args' timeout does not cover pragmas run here.
        cursor.execute(f"PRAGMA busy_timeout={Settings.SQLITE_BUSY_TIMEOUT_SECONDS * 1000}")
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    url = Settings.DATABASE_URL
    # SQLite defaults busy_timeout to 0: a writer that finds the file locked raises
    # instead of waiting. Bulk ingest writes jobs while background jobs write steps.
    connect_args = {"timeout": Settings.SQLITE_BUSY_TIMEOUT_SECONDS} if _is_sqlite(url) else {}
    engine = create_async_engine(url, echo=False, connect_args=connect_args)
    if _is_sqlite(url):
        # WAL lets the once-per-second job polling read while a write is in flight,
        # rather than each waiting out the other.
        event.listen(engine.sync_engine, "connect", _tune_sqlite_connection)
    return engine


@lru_cache(maxsize=1)
def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with _get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

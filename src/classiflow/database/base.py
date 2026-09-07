from collections.abc import AsyncGenerator, Callable
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

from classiflow.database.dialects import DialectTuning, resolve_tuning
from classiflow.settings import Settings


class Base(DeclarativeBase):
    pass


_ConnectListener = Callable[[DBAPIConnection, ConnectionPoolEntry], None]


def _connect_listener(tuning: DialectTuning) -> _ConnectListener:
    """Adapt a tuning to SQLAlchemy's connect event, which passes the pool record too.

    Returns:
        A listener that forwards each new connection to the tuning and drops the record.
    """

    def listen(dbapi_connection: DBAPIConnection, _record: ConnectionPoolEntry) -> None:
        tuning.on_connect(dbapi_connection)

    return listen


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    url = Settings.DATABASE_URL
    # Which engine this is, and what it needs, lives in database/dialects/ -- adding one
    # adds a file there and never edits this function.
    tuning = resolve_tuning(url)
    engine = create_async_engine(url, echo=False, connect_args=tuning.connect_args())
    event.listen(engine.sync_engine, "connect", _connect_listener(tuning))
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

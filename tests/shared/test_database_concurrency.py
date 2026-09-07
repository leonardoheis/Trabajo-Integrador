"""Concurrent-writer behaviour of the configured engine.

Uses a real file database throughout: `:memory:` has no file lock to contend over, so it
cannot reproduce the bug these tests pin. Contention is driven through threads on the
stdlib driver rather than asyncio -- aiosqlite serialises each connection onto its own
thread, so `asyncio.gather` over two engines interleaves cleanly and never contends.
"""

import sqlite3
import threading
import time
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from classiflow.database.base import Base, get_engine
from classiflow.settings import Settings

pytestmark = pytest.mark.anyio

_CONTENDING_WRITERS = 4
_WRITES_PER_WRITER = 30
# Long enough that a writer holds its lock past the next writer's attempt, short enough
# that four writers finish well inside a test run.
_HELD_LOCK_SECONDS = 0.002


@pytest.fixture
def database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'concurrency.db').as_posix()}"
    monkeypatch.setattr(Settings, "DATABASE_URL", url)
    get_engine.cache_clear()
    yield url
    get_engine.cache_clear()


@pytest.fixture
async def engine(database_url: str) -> AsyncGenerator[AsyncEngine, None]:
    schema_engine = create_async_engine(database_url, echo=False)
    async with schema_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await schema_engine.dispose()

    created = get_engine()
    yield created
    await created.dispose()


@pytest.fixture
def sqlite_file(tmp_path: Path) -> str:
    path = str(tmp_path / "contention.db")
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE writes (value INTEGER)")
        connection.commit()
    finally:
        connection.close()
    return path


def _write_repeatedly(path: str, *, tune: bool, failures: list[str]) -> None:
    connection = sqlite3.connect(path, timeout=0)
    if tune:
        connection.execute(f"PRAGMA busy_timeout={Settings.SQLITE_BUSY_TIMEOUT_SECONDS * 1000}")
        connection.execute("PRAGMA journal_mode=WAL")
    try:
        for value in range(_WRITES_PER_WRITER):
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO writes VALUES (?)", (value,))
            time.sleep(_HELD_LOCK_SECONDS)
            connection.commit()
    except sqlite3.OperationalError as error:
        failures.append(str(error))
    finally:
        connection.close()


def _contend(path: str, *, tune: bool) -> list[str]:
    """Run overlapping write transactions against one file.

    Returns:
        The messages of any OperationalErrors the writers raised; empty when none did.
    """
    failures: list[str] = []
    writers = [
        threading.Thread(
            target=_write_repeatedly,
            args=(path,),
            kwargs={"tune": tune, "failures": failures},
        )
        for _ in range(_CONTENDING_WRITERS)
    ]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join()
    return failures


class TestConcurrentWriters:
    def test_untuned_writers_reproduce_the_bug(self, sqlite_file: str) -> None:
        """Guards the tuned test below: without the pragmas the contention must fail."""
        assert _contend(sqlite_file, tune=False)

    def test_tuned_writers_do_not_raise_database_is_locked(self, sqlite_file: str) -> None:
        assert not _contend(sqlite_file, tune=True)


class TestEngineConfiguration:
    async def test_journal_mode_is_wal(self, engine: AsyncEngine) -> None:
        async with engine.connect() as connection:
            result = await connection.execute(text("PRAGMA journal_mode"))
            assert result.scalar_one() == "wal"

    async def test_busy_timeout_is_applied(self, engine: AsyncEngine) -> None:
        async with engine.connect() as connection:
            result = await connection.execute(text("PRAGMA busy_timeout"))
            assert result.scalar_one() == Settings.SQLITE_BUSY_TIMEOUT_SECONDS * 1000


class TestOperationalErrorStillPropagates:
    async def test_a_genuine_sql_error_is_not_swallowed(self, engine: AsyncEngine) -> None:
        """The busy timeout must not mask errors that waiting cannot fix."""
        with pytest.raises(OperationalError):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT * FROM table_that_does_not_exist"))
